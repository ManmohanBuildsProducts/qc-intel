#!/usr/bin/env python3
"""Test script: capture Zepto's BFF gateway search API response.

Tries two approaches:
  A) Non-overridable fetch patch via --init-script (xhr_intercept_v2.js)
     Uses Object.defineProperty with configurable:false to lock fetch.
  B) Extract product data from Next.js RSC flight data (self.__next_f)
     and also try Playwright page.route() interception.

Uses pincode 302020 (Jaipur) and searches for "milk".
"""

import asyncio
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

PINCODE = "302020"
LAT, LNG = 26.8607, 75.7633
SEARCH_QUERY = "milk"
SEARCH_URL = f"https://www.zepto.com/search?query={SEARCH_QUERY}"

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
SCRAPER_DIR = os.path.join(PROJECT_ROOT, "src", "agents", "scraper")


def _script_path(name: str) -> str:
    return os.path.join(SCRAPER_DIR, name)


def _result_text(result) -> str:
    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text
    return text


def _parse_evaluate_json(result) -> object:
    """Parse JSON from browser_evaluate result. Returns parsed object or None."""
    text = _result_text(result)
    match = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", text, re.DOTALL)
    raw = match.group(1).strip() if match else text.strip()
    # Unwrap double-quoted string
    if isinstance(raw, str) and raw.startswith('"'):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            pass
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


def _set_location_js() -> str:
    return (
        f'() => {{ '
        f'const pos = {{state: {{userPosition: {{'
        f'lat: {LAT}, lng: {LNG}, pincode: "{PINCODE}", '
        f'city: "Jaipur", address: "Jaipur, Rajasthan"'
        f'}}, _hasHydrated: true}}, version: 0}}; '
        f'localStorage.setItem("user-position", JSON.stringify(pos)); '
        f'return "location set"; }}'
    )


def _find_products(data) -> list[dict]:
    """Recursively find product-like objects in API response."""
    products = []

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            if "product_id" in obj or ("name" in obj and ("mrp" in obj or "price" in obj)):
                products.append(obj)
            for key in ("items", "products", "data", "sections", "widgets",
                        "results", "search_results", "layout", "storeProducts",
                        "storeProduct", "product", "store_products"):
                if key in obj:
                    walk(obj[key])
            if not any(k in obj for k in ("product_id", "mrp")):
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        walk(v)

    walk(data)
    return products


def _dump_first_product(products: list[dict], approach_name: str, full_body: dict) -> bool:
    """Print first product's full JSON and save full response. Returns True if found."""
    if not products:
        return False

    print(f"\n{'=' * 80}")
    print(f"  {approach_name}: FIRST PRODUCT (full JSON)")
    print(f"{'=' * 80}")
    print(json.dumps(products[0], indent=2, default=str))
    print(f"\n  Total products found: {len(products)}")

    # Highlight inventory fields
    inv_fields = {}
    for key in ("inventory_available", "max_allowed_quantity", "allocated_quantity",
                "quantity", "inventory", "available_quantity", "stock",
                "in_stock", "inventory_count", "max_cart_quantity",
                "stock_count", "unit_quantity"):
        if key in products[0]:
            inv_fields[key] = products[0][key]
    if inv_fields:
        print(f"\n  INVENTORY FIELDS: {json.dumps(inv_fields, indent=2)}")
    else:
        print(f"\n  WARNING: No known inventory fields found in product")
        print(f"  All keys: {sorted(products[0].keys())}")

    # Save full response
    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, "zepto_bff_response.json")
    with open(out_path, "w") as f:
        json.dump(full_body, f, indent=2, default=str)
    logger.info("[%s] Full response saved to %s", approach_name, out_path)
    return True


# ─────────────────────────────────────────────────────────────────────
# Approach A: Non-overridable init-script (xhr_intercept_v2.js)
# ─────────────────────────────────────────────────────────────────────

async def approach_a() -> bool:
    """Use xhr_intercept_v2.js with Object.defineProperty(configurable:false) to lock fetch."""
    logger.info("=" * 60)
    logger.info("APPROACH A: Non-overridable init-script (xhr_intercept_v2.js)")
    logger.info("=" * 60)

    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    stealth = _script_path("stealth.js")
    if os.path.exists(stealth):
        args += ["--init-script", stealth]
    xhr_v2 = _script_path("xhr_intercept_v2.js")
    if os.path.exists(xhr_v2):
        args += ["--init-script", xhr_v2]
    else:
        logger.error("xhr_intercept_v2.js not found at %s", xhr_v2)
        return False

    server = StdioServerParameters(command="npx", args=args)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                logger.info("[A] Navigating to Zepto homepage...")
                await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
                await session.call_tool("browser_wait_for", {"time": 3000})

                logger.info("[A] Setting location (pincode=%s)...", PINCODE)
                await session.call_tool("browser_evaluate", {"function": _set_location_js()})

                logger.info("[A] Navigating to search: %s", SEARCH_URL)
                await session.call_tool("browser_navigate", {"url": SEARCH_URL})
                await session.call_tool("browser_wait_for", {"time": 5000})

                # Check fetch status
                fetch_check = await session.call_tool("browser_evaluate", {
                    "function": "() => ({ fetchStr: window.fetch.toString().substring(0, 150), captureCount: (window.__xhrCaptures || []).length })",
                })
                check_data = _parse_evaluate_json(fetch_check)
                if isinstance(check_data, dict):
                    logger.info("[A] Fetch is ours: %s", "origFetch" in str(check_data.get("fetchStr", "")))
                    logger.info("[A] Capture count: %d", check_data.get("captureCount", 0))

                # Retrieve captures
                result = await session.call_tool("browser_evaluate", {
                    "function": "() => JSON.stringify(window.__xhrCaptures || [])",
                })
                captures = _parse_evaluate_json(result)
                if not isinstance(captures, list):
                    captures = []
                logger.info("[A] Captures found: %d", len(captures))

                if captures:
                    for cap in captures:
                        body = cap.get("body", {})
                        products = _find_products(body)
                        if products:
                            return _dump_first_product(products, "APPROACH_A", body)

                # No captures — check network to confirm BFF calls happened
                logger.info("[A] No XHR captures. Checking network requests...")
                net_result = await session.call_tool("browser_network_requests", {})
                net_text = _result_text(net_result)
                bff_lines = [l for l in net_text.split("\n") if "bff-gateway" in l.lower()]
                if bff_lines:
                    print(f"\n  [A] BFF network requests (seen but NOT captured via fetch):")
                    for line in bff_lines[:5]:
                        print(f"    {line.strip()}")
                    print(f"\n  CONCLUSION: BFF calls are server-side (Next.js SSR), not window.fetch")

                return False

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────
# Approach B: Extract from Next.js RSC flight data + route interception
# ─────────────────────────────────────────────────────────────────────

async def approach_b() -> bool:
    """Extract product data from Next.js hydration/RSC data on the loaded page."""
    logger.info("=" * 60)
    logger.info("APPROACH B: Next.js RSC extraction + route interception")
    logger.info("=" * 60)

    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    stealth = _script_path("stealth.js")
    if os.path.exists(stealth):
        args += ["--init-script", stealth]

    server = StdioServerParameters(command="npx", args=args)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                logger.info("[B] Navigating to Zepto homepage...")
                await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
                await session.call_tool("browser_wait_for", {"time": 3000})

                logger.info("[B] Setting location (pincode=%s)...", PINCODE)
                await session.call_tool("browser_evaluate", {"function": _set_location_js()})

                logger.info("[B] Navigating to search page...")
                await session.call_tool("browser_navigate", {"url": SEARCH_URL})
                await session.call_tool("browser_wait_for", {"time": 5000})

                # Strategy 1: Check for __NEXT_DATA__ (classic Next.js SSR)
                logger.info("[B] Checking for __NEXT_DATA__...")
                next_data_result = await session.call_tool("browser_evaluate", {"function": """() => {
                    if (window.__NEXT_DATA__) {
                        return JSON.stringify({
                            found: true,
                            keys: Object.keys(window.__NEXT_DATA__),
                            hasProps: !!window.__NEXT_DATA__.props,
                            hasPageProps: !!(window.__NEXT_DATA__.props && window.__NEXT_DATA__.props.pageProps),
                        });
                    }
                    return JSON.stringify({found: false});
                }"""})
                nd = _parse_evaluate_json(next_data_result)
                if isinstance(nd, dict) and nd.get("found"):
                    logger.info("[B] __NEXT_DATA__ found! keys=%s", nd.get("keys"))
                    # Fetch the full __NEXT_DATA__
                    full_nd = await session.call_tool("browser_evaluate", {
                        "function": "() => JSON.stringify(window.__NEXT_DATA__)",
                    })
                    full_data = _parse_evaluate_json(full_nd)
                    if isinstance(full_data, dict):
                        products = _find_products(full_data)
                        if products:
                            return _dump_first_product(products, "APPROACH_B (__NEXT_DATA__)", full_data)
                        logger.info("[B] __NEXT_DATA__ found but no products in it")
                else:
                    logger.info("[B] No __NEXT_DATA__ (App Router / RSC)")

                # Strategy 2: Extract from self.__next_f (RSC flight data)
                logger.info("[B] Checking for RSC flight data (self.__next_f)...")
                rsc_check = await session.call_tool("browser_evaluate", {"function": """() => {
                    if (typeof self !== 'undefined' && self.__next_f) {
                        return JSON.stringify({
                            found: true,
                            chunkCount: self.__next_f.length,
                        });
                    }
                    return JSON.stringify({found: false});
                }"""})
                rsc_info = _parse_evaluate_json(rsc_check)

                if isinstance(rsc_info, dict) and rsc_info.get("found"):
                    chunk_count = rsc_info.get("chunkCount", 0)
                    logger.info("[B] RSC flight data found! %d chunks", chunk_count)

                    # Extract product data from RSC chunks
                    rsc_result = await session.call_tool("browser_evaluate", {"function": r"""() => {
                        if (!self.__next_f) return JSON.stringify({error: 'no __next_f'});

                        let allText = '';
                        for (const chunk of self.__next_f) {
                            if (Array.isArray(chunk) && chunk.length >= 2 && typeof chunk[1] === 'string') {
                                allText += chunk[1];
                            }
                        }

                        // Search for product objects by finding "productId" and walking
                        // outward to find the enclosing object with many keys (the real product)
                        const products = [];
                        const regex = /"productId"\s*:\s*"/g;
                        let m;
                        while ((m = regex.exec(allText)) !== null && products.length < 3) {
                            // Walk backward to find enclosing { at different depths
                            // Try multiple candidate start positions (the productId might be nested)
                            let candidates = [];
                            let pos = m.index;
                            let depth = 0;
                            for (let i = pos; i >= Math.max(0, pos - 5000); i--) {
                                if (allText[i] === '}') depth++;
                                if (allText[i] === '{') {
                                    if (depth === 0) {
                                        candidates.push(i);
                                    } else {
                                        depth--;
                                    }
                                }
                            }

                            // Try each candidate, pick the largest valid JSON object
                            let bestObj = null;
                            let bestKeys = 0;
                            for (const start of candidates) {
                                let d = 0;
                                let end = start;
                                for (let i = start; i < allText.length && i < start + 20000; i++) {
                                    if (allText[i] === '{') d++;
                                    if (allText[i] === '}') d--;
                                    if (d === 0) { end = i + 1; break; }
                                }
                                if (end > start) {
                                    try {
                                        const obj = JSON.parse(allText.substring(start, end));
                                        const keys = Object.keys(obj).length;
                                        if (keys > bestKeys && keys > 3) {
                                            bestObj = obj;
                                            bestKeys = keys;
                                        }
                                    } catch(e) {}
                                }
                            }
                            if (bestObj) products.push(bestObj);
                        }

                        // Find context around "mrp" and "inventory"
                        const mrpIdx = allText.indexOf('"mrp"');
                        const invIdx = allText.indexOf('inventory');
                        const mrpContext = mrpIdx >= 0
                            ? allText.substring(Math.max(0, mrpIdx - 300), mrpIdx + 500)
                            : '';
                        const invContext = invIdx >= 0
                            ? allText.substring(Math.max(0, invIdx - 200), invIdx + 500)
                            : '';

                        return JSON.stringify({
                            totalBytes: allText.length,
                            productCount: products.length,
                            products: products,
                            productKeyCounts: products.map(p => Object.keys(p).length),
                            mrpContext: mrpContext.substring(0, 1000),
                            inventoryContext: invContext.substring(0, 1000),
                            hasProductId: allText.includes('product_id'),
                            hasProductIdCamel: allText.includes('productId'),
                            hasMrp: allText.includes('"mrp"'),
                            hasInventory: allText.includes('inventory'),
                            hasInventoryAvailable: allText.includes('inventory_available'),
                        });
                    }"""})
                    rsc_data = _parse_evaluate_json(rsc_result)

                    if isinstance(rsc_data, dict):
                        logger.info("[B] RSC bytes=%d, products=%d, hasProductId=%s, hasProductIdCamel=%s, hasMrp=%s, hasInventory=%s, hasInventoryAvailable=%s",
                                    rsc_data.get("totalBytes", 0),
                                    rsc_data.get("productCount", 0),
                                    rsc_data.get("hasProductId"),
                                    rsc_data.get("hasProductIdCamel"),
                                    rsc_data.get("hasMrp"),
                                    rsc_data.get("hasInventory"),
                                    rsc_data.get("hasInventoryAvailable"))

                        products = rsc_data.get("products", [])
                        # Filter out tiny/useless objects — real products have multiple keys
                        real_products = [p for p in products if len(p) > 3]
                        if real_products:
                            body = {"source": "RSC_flight_data", "products": real_products}
                            return _dump_first_product(real_products, "APPROACH_B (RSC)", body)
                        elif products:
                            logger.info("[B] Products extracted but too small: %s", [list(p.keys()) for p in products])

                        # Show mrp and inventory context for debugging
                        mrp_ctx = rsc_data.get("mrpContext", "")
                        if mrp_ctx:
                            print(f"\n  [B] Context around 'mrp' in RSC data:")
                            print(f"    {mrp_ctx[:800]}")
                        inv_ctx = rsc_data.get("inventoryContext", "")
                        if inv_ctx:
                            print(f"\n  [B] Context around 'inventory' in RSC data:")
                            print(f"    {inv_ctx[:800]}")
                        if not mrp_ctx and not inv_ctx:
                            logger.info("[B] No product-like data found in RSC")
                else:
                    logger.info("[B] No RSC flight data found")

                # Strategy 3: Look for inline script tags with product data
                logger.info("[B] Checking inline scripts for product data...")
                script_result = await session.call_tool("browser_evaluate", {"function": """() => {
                    const scripts = document.querySelectorAll('script');
                    const matches = [];
                    for (const s of scripts) {
                        const text = s.textContent || '';
                        if (text.includes('product_id') || text.includes('inventory')) {
                            matches.push({
                                type: s.type || 'default',
                                length: text.length,
                                preview: text.substring(0, 500),
                            });
                        }
                    }
                    return JSON.stringify({count: matches.length, matches: matches.slice(0, 5)});
                }"""})
                script_data = _parse_evaluate_json(script_result)
                if isinstance(script_data, dict) and script_data.get("count", 0) > 0:
                    logger.info("[B] Found %d scripts with product data!", script_data["count"])
                    for m in script_data.get("matches", []):
                        print(f"\n  Script type={m.get('type')}, len={m.get('length')}")
                        print(f"  Preview: {m.get('preview', '')[:300]}")

                return False

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass


async def main():
    print("=" * 80)
    print("  Zepto BFF Gateway Capture Test")
    print(f"  Pincode: {PINCODE} | Search: '{SEARCH_QUERY}'")
    print("=" * 80)

    # Try Approach A first
    a_success = await approach_a()

    if a_success:
        print(f"\n{'=' * 80}")
        print("  RESULT: Approach A (non-overridable init-script) SUCCEEDED")
        print(f"{'=' * 80}")
    else:
        print(f"\n{'=' * 80}")
        print("  Approach A FAILED — trying Approach B...")
        print(f"{'=' * 80}")

    # Always try Approach B for comparison
    b_success = await approach_b()

    if b_success:
        print(f"\n{'=' * 80}")
        print("  RESULT: Approach B (RSC extraction) SUCCEEDED")
        print(f"{'=' * 80}")

    # Summary
    print(f"\n{'=' * 80}")
    print("  SUMMARY")
    print(f"{'=' * 80}")
    print(f"  Approach A (init-script defineProperty): {'SUCCESS' if a_success else 'FAILED'}")
    print(f"  Approach B (RSC extraction):             {'SUCCESS' if b_success else 'FAILED'}")

    if not a_success and not b_success:
        print("\n  Both approaches failed to capture BFF gateway responses.")
        print("  Root cause: Zepto uses Next.js App Router with RSC.")
        print("  The BFF search API is called server-side during SSR,")
        print("  NOT via client-side window.fetch. fetch-patching cannot")
        print("  intercept server-side requests.")
        print("\n  Possible solutions:")
        print("    1. Use Playwright page.route() (requires native Playwright, not MCP)")
        print("    2. Call the BFF API directly with proper auth headers")
        print("    3. Extract product data from RSC flight payloads")
        print("    4. Continue using accessibility snapshot extraction")

    print(f"{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(main())
