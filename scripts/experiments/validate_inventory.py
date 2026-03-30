#!/usr/bin/env python3
"""Phase 1: Validate what inventory fields Zepto & Instamart APIs actually return.

Scrapes one search term per platform, dumps the COMPLETE raw JSON for the first
3 products so we can see every key the API returns. No DB writes, no parsing —
just raw field discovery.

Usage:
    python scripts/validate_inventory.py                    # both platforms
    python scripts/validate_inventory.py --platform zepto   # zepto only
    python scripts/validate_inventory.py --platform instamart
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import re

# Add project root to path for src imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Jaipur Mansarovar — confirmed triple-overlap pincode
PINCODE = "302020"
LAT, LNG = 26.8607, 75.7633
SEARCH_TERM = "milk"

# Inventory-related keys to highlight in output
INV_KEYS = {
    "quantity", "inventory", "available_quantity", "inventory_count",
    "stock", "stock_count", "in_stock", "max_cart_quantity",
    "max_selectable_quantity", "maxSelectableQuantity",
    "unavailable_quantity", "available",
}


def _script_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", "src", "agents", "scraper", name)


def _build_server() -> StdioServerParameters:
    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    stealth = _script_path("stealth.js")
    if os.path.exists(stealth):
        args += ["--init-script", stealth]
    xhr = _script_path("xhr_intercept.js")
    if os.path.exists(xhr):
        args += ["--init-script", xhr]
    return StdioServerParameters(command="npx", args=args)


def _result_text(result) -> str:
    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text
    return text


def _parse_captures(result) -> list[dict]:
    text = _result_text(result)
    match = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", text, re.DOTALL)
    if match:
        raw = match.group(1).strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                pass
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return []
        return raw if isinstance(raw, list) else []
    return []


def _walk_for_products(obj: dict | list, max_products: int = 5) -> list[dict]:
    """Walk nested JSON to find product-like objects (have name + price/mrp)."""
    products = []

    def walk(o):
        if len(products) >= max_products:
            return
        if isinstance(o, list):
            for item in o:
                walk(item)
        elif isinstance(o, dict):
            has_name = "name" in o or "product_name" in o or "display_name" in o
            has_price = "mrp" in o or "price" in o or "discounted_price" in o
            has_id = "product_id" in o or "id" in o
            if has_name and (has_price or has_id):
                products.append(o)
            else:
                for key in ("items", "products", "data", "sections", "widgets", "product"):
                    if key in o:
                        walk(o[key])
                # Also walk other dict values that are lists/dicts
                for k, v in o.items():
                    if k not in ("items", "products", "data", "sections", "widgets", "product"):
                        if isinstance(v, (list, dict)):
                            walk(v)
    walk(obj)
    return products


def _deep_scan_inventory(obj, indent: str = "", path: str = "", max_depth: int = 10, depth: int = 0, _found: set | None = None) -> None:
    """Recursively scan for ANY key that could be inventory/stock related."""
    if _found is None:
        _found = set()
    if depth >= max_depth:
        return
    inv_keywords = {"inventory", "stock", "quantity", "available", "sellable",
                    "count", "remaining", "supply", "warehouse", "max_order",
                    "maxorder", "maxqty", "sold", "units"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_lower = k.lower().replace("-", "_").replace(" ", "_")
            current_path = f"{path}.{k}" if path else k
            # Check if key name contains inventory-related words
            if any(kw in k_lower for kw in inv_keywords):
                sig = f"{current_path}={v!r}"
                if sig not in _found:
                    _found.add(sig)
                    vtype = type(v).__name__
                    print(f"{indent}*** {current_path}: {v!r}  ({vtype})")
            if isinstance(v, (dict, list)):
                _deep_scan_inventory(v, indent, current_path, max_depth, depth + 1, _found)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # Only scan first 3 items
            _deep_scan_inventory(item, indent, f"{path}[{i}]", max_depth, depth + 1, _found)


def _dump_structure(obj, indent: str = "", max_depth: int = 5, depth: int = 0) -> None:
    """Print a summary of nested dict/list structure to help find products."""
    if depth >= max_depth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                print(f"{indent}{k}: dict({len(v)} keys: {list(v.keys())[:8]})")
                _dump_structure(v, indent + "  ", max_depth, depth + 1)
            elif isinstance(v, list):
                sample_type = type(v[0]).__name__ if v else "empty"
                print(f"{indent}{k}: list[{len(v)}] of {sample_type}")
                if v and isinstance(v[0], dict):
                    print(f"{indent}  [0] keys: {list(v[0].keys())[:10]}")
                    _dump_structure(v[0], indent + "  ", max_depth, depth + 1)
            else:
                vstr = repr(v)
                if len(vstr) > 80:
                    vstr = vstr[:80] + "..."
                print(f"{indent}{k}: {type(v).__name__} = {vstr}")
    elif isinstance(obj, list) and obj:
        if isinstance(obj[0], dict):
            print(f"{indent}[0] keys: {list(obj[0].keys())[:10]}")
            _dump_structure(obj[0], indent + "  ", max_depth, depth + 1)


def _print_product(idx: int, prod: dict, platform: str) -> None:
    name = prod.get("name") or prod.get("product_name") or prod.get("display_name", "?")
    print(f"\n{'='*70}")
    print(f"  [{platform}] Product {idx}: {name}")
    print(f"{'='*70}")

    # All keys
    print(f"\n  ALL KEYS ({len(prod)}): {sorted(prod.keys())}")

    # Inventory-related fields
    inv_fields = {k: prod[k] for k in prod if k.lower().replace("-", "_") in INV_KEYS or k in INV_KEYS}
    if inv_fields:
        print(f"\n  INVENTORY-RELATED FIELDS:")
        for k, v in inv_fields.items():
            vtype = type(v).__name__
            print(f"    {k}: {v!r}  ({vtype})")
    else:
        print(f"\n  INVENTORY-RELATED FIELDS: *** NONE FOUND ***")

    # Pack size fields
    size_fields = {k: prod[k] for k in prod if k in (
        "unit_quantity", "unit", "packSize", "weight", "quantity", "pack_size",
    )}
    if size_fields:
        print(f"\n  PACK SIZE FIELDS:")
        for k, v in size_fields.items():
            vtype = type(v).__name__
            print(f"    {k}: {v!r}  ({vtype})")

    # Full raw JSON (truncated for readability)
    raw = json.dumps(prod, indent=2, default=str)
    if len(raw) > 2000:
        raw = raw[:2000] + "\n    ... (truncated)"
    print(f"\n  RAW JSON:\n{raw}")


async def scrape_zepto(session: ClientSession) -> None:
    logger.info("=== ZEPTO: Setting location %s (%.4f, %.4f) ===", PINCODE, LAT, LNG)
    await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
    await session.call_tool("browser_wait_for", {"time": 3000})

    # Set location
    await session.call_tool("browser_evaluate", {"function": (
        f'() => {{ '
        f'const pos = {{state: {{userPosition: {{'
        f'lat: {LAT}, lng: {LNG}, pincode: "{PINCODE}", '
        f'city: "Jaipur", address: "Jaipur, Rajasthan"'
        f'}}, _hasHydrated: true}}, version: 0}}; '
        f'localStorage.setItem("user-position", JSON.stringify(pos)); '
        f'return "location set"; }}'
    )})

    # Reload to pick up location
    await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
    await session.call_tool("browser_wait_for", {"time": 3000})

    # Clear XHR captures before search
    await session.call_tool("browser_evaluate", {
        "function": "() => { window.__xhrCaptures = []; return 'cleared'; }",
    })

    # Navigate to search — may show "Select Location" modal
    url = f"https://www.zepto.com/search?query={SEARCH_TERM}"
    logger.info("Searching: %s", url)
    await session.call_tool("browser_navigate", {"url": url})
    await session.call_tool("browser_wait_for", {"time": 3000})

    # Check if "Select Location" button is visible — click it like the production scraper
    snap_result = await session.call_tool("browser_snapshot", {})
    snap_text = _result_text(snap_result)
    if "Select Location" in snap_text:
        logger.info("Clicking 'Select Location' to trigger product loading...")
        try:
            await session.call_tool("browser_click", {
                "element": "Select Location button", "ref": "",
            })
            await session.call_tool("browser_wait_for", {"time": 3000})
        except Exception as e:
            logger.warning("Could not click Select Location: %s", e)

    # Scroll to trigger lazy loading
    await session.call_tool("browser_evaluate", {
        "function": "() => { window.scrollTo(0, 1000); return 'scrolled'; }",
    })
    await session.call_tool("browser_wait_for", {"time": 3000})

    # Retrieve captures
    result = await session.call_tool("browser_evaluate", {
        "function": "() => JSON.stringify(window.__xhrCaptures || [])",
    })
    captures = _parse_captures(result)

    if not captures:
        logger.warning("ZEPTO: No XHR captures! Fetch interception may have failed.")
        # Try snapshot as diagnostic
        snap = await session.call_tool("browser_snapshot", {})
        snap_text = _result_text(snap)
        logger.info("Snapshot preview (first 500 chars): %s", snap_text[:500])
        return

    logger.info("ZEPTO: Got %d XHR captures", len(captures))
    for ci, capture in enumerate(captures):
        body = capture.get("body", {})
        logger.info("  Capture %d: url=%s keys=%s", ci, capture.get("url", "?")[:80], list(body.keys())[:10])

        # Dump response structure to see where inventory might be hiding
        print(f"\n  RESPONSE STRUCTURE WALKTHROUGH:")
        _dump_structure(body, "  ", max_depth=8)

        # Also dump first product's COMPLETE raw JSON (up to 20KB)
        products = _walk_for_products(body, max_products=1)
        if products:
            prod = products[0]
            name = prod.get("name") or prod.get("product_name", "?")
            raw = json.dumps(prod, indent=2, default=str)
            if len(raw) > 20000:
                raw = raw[:20000] + "\n... (truncated)"
            print(f"\n  FIRST PRODUCT COMPLETE RAW JSON ({name[:40]}):\n{raw}")

            # Search ALL keys recursively for inventory-like fields
            print(f"\n  DEEP INVENTORY SCAN (all nested fields):")
            _deep_scan_inventory(prod, "  ")

        # Also scan the full response body for inventory-like keys
        print(f"\n  FULL RESPONSE INVENTORY SCAN:")
        _deep_scan_inventory(body, "  ", max_depth=10)


async def scrape_instamart(session: ClientSession) -> None:
    logger.info("=== INSTAMART: Setting location %s (%.4f, %.4f) ===", PINCODE, LAT, LNG)
    await session.call_tool("browser_navigate", {"url": "https://www.swiggy.com"})
    await session.call_tool("browser_wait_for", {"time": 3000})

    # Set location cookies
    loc_json = (
        f'{{"address":"Jaipur","lat":{LAT},"lng":{LNG},'
        f'"id":"","annotation":"","name":"Jaipur"}}'
    )
    await session.call_tool("browser_evaluate", {"function": (
        f'() => {{ '
        f'const loc = encodeURIComponent(\'{loc_json}\'); '
        f'document.cookie = "userLocation=" + loc + ";path=/;max-age=86400"; '
        f'document.cookie = "_dl={LAT};path=/;max-age=86400"; '
        f'return "location set"; }}'
    )})

    # Clear + search
    await session.call_tool("browser_evaluate", {
        "function": "() => { window.__xhrCaptures = []; return 'cleared'; }",
    })
    url = f"https://www.swiggy.com/instamart/search?custom_back=true&query={SEARCH_TERM}"
    logger.info("Searching: %s", url)
    await session.call_tool("browser_navigate", {"url": url})
    await session.call_tool("browser_wait_for", {"time": 5000})

    # Retrieve captures
    result = await session.call_tool("browser_evaluate", {
        "function": "() => JSON.stringify(window.__xhrCaptures || [])",
    })
    captures = _parse_captures(result)

    if not captures:
        logger.warning("INSTAMART: No XHR captures! Fetch interception may have failed.")
        snap = await session.call_tool("browser_snapshot", {})
        snap_text = _result_text(snap)
        logger.info("Snapshot preview (first 500 chars): %s", snap_text[:500])
        return

    logger.info("INSTAMART: Got %d XHR captures", len(captures))
    for ci, capture in enumerate(captures):
        body = capture.get("body", {})
        logger.info("  Capture %d: url=%s", ci, capture.get("url", "?")[:80])

        # Walk the Instamart nested structure: data.data.widgets[].data.products[].product
        # Dump raw body structure for debugging
        # Try the Instamart-specific extraction path first
        from src.agents.scraper.instamart import InstamartScraper
        im_products = InstamartScraper._extract_from_api_response(body, "Dairy & Bread")
        if im_products:
            print(f"\n  Instamart extractor found {len(im_products)} products")
            for i, prod in enumerate(im_products[:3], 1):
                _print_product(i, prod, "INSTAMART-EXTRACTED")
        else:
            logger.info("  Instamart extractor found 0 products — API structure may differ")

        # Generic walker
        products = _walk_for_products(body, max_products=5)
        if products:
            print(f"\n  Generic walker found {len(products)} products")
            for i, prod in enumerate(products[:3], 1):
                _print_product(i, prod, "INSTAMART")
        else:
            logger.warning("  Generic walker also found 0 products")

        # Dump structure summary: walk the body to find keys at each level
        print(f"\n  RESPONSE STRUCTURE WALKTHROUGH:")
        _dump_structure(body, "  ", max_depth=6)


async def run(platforms: list[str]) -> None:
    server = _build_server()
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                if "zepto" in platforms:
                    await scrape_zepto(session)
                    print("\n" + "~" * 70 + "\n")

                if "instamart" in platforms:
                    # Need a fresh browser for different domain
                    await session.call_tool("browser_close", {})

            except Exception as e:
                logger.error("Error during scrape: %s", e, exc_info=True)
            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass

    # Instamart needs its own browser session (different domain cookies)
    if "instamart" in platforms:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    await scrape_instamart(session)
                except Exception as e:
                    logger.error("Error during Instamart scrape: %s", e, exc_info=True)
                finally:
                    try:
                        await session.call_tool("browser_close", {})
                    except Exception:
                        pass


def main():
    parser = argparse.ArgumentParser(description="Validate inventory fields from Zepto/Instamart APIs")
    parser.add_argument(
        "--platform", choices=["zepto", "instamart", "both"], default="both",
        help="Which platform to test (default: both)",
    )
    args = parser.parse_args()

    platforms = ["zepto", "instamart"] if args.platform == "both" else [args.platform]

    print(f"\n{'#' * 70}")
    print(f"  INVENTORY FIELD VALIDATION — Phase 1")
    print(f"  Pincode: {PINCODE} | Search: '{SEARCH_TERM}' | Platforms: {platforms}")
    print(f"{'#' * 70}\n")

    asyncio.run(run(platforms))

    print(f"\n{'#' * 70}")
    print(f"  DONE — Check output above for INVENTORY-RELATED FIELDS")
    print(f"  If fields are numeric: real inventory exists → fix works")
    print(f"  If fields are missing/string: need proxy signals")
    print(f"{'#' * 70}\n")


if __name__ == "__main__":
    main()
