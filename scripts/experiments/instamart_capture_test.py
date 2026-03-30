"""Instamart API capture test — dumps raw XHR response and scans for inventory fields.

Uses the same MCP + XHR interception setup as instamart_fast.py.
Navigates to Instamart search for "milk" at pincode 302020 (Jaipur).
Dumps complete raw API response to data/instamart_raw_capture.json.
Prints structure walkthrough and scans for inventory-related keywords.
"""

import asyncio
import json
import logging
import os
import sys

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Jaipur location
PINCODE = "302020"
LAT = 26.8607
LNG = 75.7633
CITY = "Jaipur"
SEARCH_TERM = "milk"

# Keywords to scan for inventory-related fields
INVENTORY_KEYWORDS = {
    "inventory", "stock", "quantity", "available", "sellable",
    "count", "remaining", "supply", "units", "qty", "left",
    "max_selectable", "maxselectable", "max_qty", "maxqty",
}


def _xhr_intercept_path() -> str:
    return os.path.join(PROJECT_ROOT, "src", "agents", "scraper", "xhr_intercept.js")


def _stealth_script_path() -> str:
    return os.path.join(PROJECT_ROOT, "src", "agents", "scraper", "stealth.js")


def _build_server() -> StdioServerParameters:
    # Drop --headless so we can see what's happening and avoid security restrictions
    args = ["@playwright/mcp@latest", "--browser", "chromium", "--isolated"]
    stealth = _stealth_script_path()
    if os.path.exists(stealth):
        args += ["--init-script", stealth]
        logger.info("Using stealth script: %s", stealth)
    xhr = _xhr_intercept_path()
    if os.path.exists(xhr):
        args += ["--init-script", xhr]
        logger.info("Using XHR intercept script: %s", xhr)
    return StdioServerParameters(command="npx", args=args)


def _result_text(result) -> str:
    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text
    return text


def _parse_captures(result) -> list[dict]:
    import re
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


def walk_structure(obj, prefix="", depth=0, max_depth=5):
    """Print the nested key structure of a JSON object."""
    if depth > max_depth:
        print(f"{'  ' * depth}{prefix}... (max depth reached)")
        return
    if isinstance(obj, dict):
        for key in list(obj.keys())[:30]:  # Limit keys shown per level
            val = obj[key]
            type_name = type(val).__name__
            if isinstance(val, dict):
                print(f"{'  ' * depth}{prefix}{key}: {{}} ({len(val)} keys)")
                walk_structure(val, "", depth + 1, max_depth)
            elif isinstance(val, list):
                item_type = type(val[0]).__name__ if val else "empty"
                print(f"{'  ' * depth}{prefix}{key}: [] (len={len(val)}, items={item_type})")
                if val and isinstance(val[0], dict):
                    walk_structure(val[0], "[0].", depth + 1, max_depth)
            else:
                # Truncate long strings
                display = str(val)
                if len(display) > 80:
                    display = display[:80] + "..."
                print(f"{'  ' * depth}{prefix}{key}: {type_name} = {display}")
        if len(obj) > 30:
            print(f"{'  ' * depth}... and {len(obj) - 30} more keys")
    elif isinstance(obj, list) and obj:
        if isinstance(obj[0], dict):
            walk_structure(obj[0], "[0].", depth, max_depth)
        else:
            print(f"{'  ' * depth}{prefix}[0]: {type(obj[0]).__name__} = {obj[0]}")


def scan_inventory_fields(obj, path="", results=None):
    """Recursively scan for any key containing inventory-related keywords."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            current_path = f"{path}.{key}" if path else key
            key_lower = key.lower()
            if any(kw in key_lower for kw in INVENTORY_KEYWORDS):
                results.append((current_path, type(val).__name__, repr(val)[:200]))
            scan_inventory_fields(val, current_path, results)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:5]):  # Check first 5 items
            scan_inventory_fields(item, f"{path}[{i}]", results)
    return results


async def run():
    server = _build_server()

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                # Step 1: Navigate to Swiggy homepage
                logger.info("Navigating to Swiggy homepage...")
                await session.call_tool("browser_navigate", {"url": "https://www.swiggy.com"})
                await session.call_tool("browser_wait_for", {"time": 3000})

                # Step 2: Wait for homepage to fully load, then set location cookies
                # The SecurityError happens when the page hasn't fully loaded on swiggy.com origin
                await session.call_tool("browser_wait_for", {"time": 3000})

                # Check current URL to confirm we're on swiggy.com
                snap_check = await session.call_tool("browser_snapshot", {})
                logger.info("Homepage snapshot (first 500 chars): %s", _result_text(snap_check)[:500])

                # Try setting cookies — retry with wait if security error
                loc_json = (
                    f'{{"address":"{CITY}","lat":{LAT},"lng":{LNG},'
                    f'"id":"","annotation":"","name":"{CITY}"}}'
                )

                # Use browser_run_code which has full Playwright API access for cookie setting
                cookie_js = (
                    f'() => {{ '
                    f'try {{ '
                    f'const loc = encodeURIComponent(\'{loc_json}\'); '
                    f'document.cookie = "userLocation=" + loc + ";path=/;domain=.swiggy.com;max-age=86400"; '
                    f'document.cookie = "_dl={LAT};path=/;domain=.swiggy.com;max-age=86400"; '
                    f'return "cookies set for {CITY}"; '
                    f'}} catch(e) {{ return "cookie error: " + e.message; }} }}'
                )
                cookie_result = await session.call_tool("browser_evaluate", {"function": cookie_js})
                logger.info("Cookie result: %s", _result_text(cookie_result)[:300])

                # If cookies failed, try setting via localStorage approach
                cookie_text = _result_text(cookie_result)
                if "error" in cookie_text.lower() or "denied" in cookie_text.lower():
                    logger.warning("Cookie setting failed, trying localStorage approach...")
                    ls_result = await session.call_tool("browser_evaluate", {"function": (
                        f'() => {{ '
                        f'try {{ '
                        f'localStorage.setItem("userLocation", JSON.stringify({{"address":"{CITY}","lat":{LAT},"lng":{LNG},"id":"","annotation":"","name":"{CITY}"}})); '
                        f'return "localStorage set"; '
                        f'}} catch(e) {{ return "ls error: " + e.message; }} }}'
                    )})
                    logger.info("localStorage result: %s", _result_text(ls_result)[:200])

                # Step 3: Clear previous captures
                await session.call_tool("browser_evaluate", {
                    "function": "() => { window.__xhrCaptures = []; return 'cleared'; }",
                })

                # Step 4: Navigate to search page
                url = f"https://www.swiggy.com/instamart/search?custom_back=true&query={SEARCH_TERM}"
                logger.info("Navigating to: %s", url)
                await session.call_tool("browser_navigate", {"url": url})
                await session.call_tool("browser_wait_for", {"time": 6000})

                # Step 5: Scroll to trigger more loading
                await session.call_tool("browser_evaluate", {
                    "function": "() => { window.scrollTo(0, 1500); return 'scrolled'; }",
                })
                await session.call_tool("browser_wait_for", {"time": 2000})

                # Step 6: Retrieve intercepted API responses
                result = await session.call_tool("browser_evaluate", {
                    "function": "() => JSON.stringify(window.__xhrCaptures || [])",
                })
                captures = _parse_captures(result)

                logger.info("=== CAPTURE RESULTS ===")
                logger.info("Number of captures: %d", len(captures))

                if not captures:
                    logger.warning("No XHR captures found!")
                    # Try taking a snapshot to see what's on the page
                    snap = await session.call_tool("browser_snapshot", {})
                    snap_text = _result_text(snap)
                    logger.info("Page snapshot (first 2000 chars):\n%s", snap_text[:2000])
                    return

                for i, capture in enumerate(captures):
                    cap_url = capture.get("url", "unknown")
                    status = capture.get("status", "?")
                    body = capture.get("body", {})

                    logger.info("--- Capture %d ---", i)
                    logger.info("URL: %s", cap_url[:150])
                    logger.info("Status: %s", status)
                    logger.info("Body type: %s", type(body).__name__)

                    if isinstance(body, dict):
                        logger.info("Top-level keys: %s", list(body.keys()))
                    elif isinstance(body, str):
                        # Maybe it's a JSON string
                        try:
                            body = json.loads(body)
                            capture["body"] = body
                            logger.info("Parsed string body. Top-level keys: %s", list(body.keys()))
                        except json.JSONDecodeError:
                            logger.info("Body is string (not JSON), length: %d", len(body))

                # Use the first capture with a dict body for analysis
                analysis_body = None
                for capture in captures:
                    if isinstance(capture.get("body"), dict):
                        analysis_body = capture["body"]
                        break

                if not analysis_body:
                    logger.warning("No dict-type capture body found for analysis")
                    return

                # Dump raw response to file
                dump_path = os.path.join(PROJECT_ROOT, "data", "instamart_raw_capture.json")
                # Remove existing dump so we always get fresh data
                if os.path.exists(dump_path):
                    os.remove(dump_path)
                with open(dump_path, "w") as f:
                    json.dump(analysis_body, f, indent=2, default=str)
                logger.info("Dumped raw capture to: %s", dump_path)

                # Walk the structure
                print("\n" + "=" * 70)
                print("API RESPONSE STRUCTURE WALKTHROUGH")
                print("=" * 70)
                walk_structure(analysis_body, max_depth=6)

                # Scan for inventory fields
                print("\n" + "=" * 70)
                print("INVENTORY-RELATED FIELD SCAN")
                print(f"Keywords: {sorted(INVENTORY_KEYWORDS)}")
                print("=" * 70)
                inv_results = scan_inventory_fields(analysis_body)
                if inv_results:
                    for path, type_name, val in inv_results:
                        print(f"  FOUND: {path} ({type_name}) = {val}")
                else:
                    print("  NO inventory-related fields found anywhere in the response!")

                # Also check: try the old widget path
                print("\n" + "=" * 70)
                print("PATH CHECK: Old parser path (data.widgets)")
                print("=" * 70)
                old_widgets = analysis_body.get("data", {}).get("widgets", None)
                print(f"  data.widgets = {type(old_widgets).__name__}: {repr(old_widgets)[:200] if old_widgets else 'MISSING'}")

                # Check new path: data.cards
                print("\n" + "=" * 70)
                print("PATH CHECK: New suspected path (data.cards)")
                print("=" * 70)
                new_cards = analysis_body.get("data", {}).get("cards", None)
                if new_cards is None:
                    # Maybe top-level cards?
                    new_cards = analysis_body.get("cards", None)
                if new_cards:
                    print(f"  cards found! Type: {type(new_cards).__name__}, Length: {len(new_cards) if isinstance(new_cards, list) else 'N/A'}")
                    if isinstance(new_cards, list):
                        for ci, card in enumerate(new_cards[:10]):
                            if isinstance(card, dict):
                                print(f"  cards[{ci}] keys: {list(card.keys())[:15]}")
                                # Look for product data inside cards
                                card_type = card.get("type") or card.get("cardType") or card.get("widgetType")
                                if card_type:
                                    print(f"    type/cardType: {card_type}")
                else:
                    print("  data.cards = MISSING (also checked top-level)")

                # Try to find product-like structures anywhere
                print("\n" + "=" * 70)
                print("PRODUCT SEARCH: Looking for product-like objects")
                print("=" * 70)
                _find_products(analysis_body, "root")

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass


def _find_products(obj, path, depth=0, found_count=[0]):
    """Recursively look for objects that look like products (have name + price fields)."""
    if depth > 8 or found_count[0] >= 5:
        return
    if isinstance(obj, dict):
        # Check if this looks like a product
        has_name = any(k in obj for k in ("name", "display_name", "productName"))
        has_price = any(k in obj for k in ("price", "mrp", "offer_price", "pricing"))
        if has_name and has_price:
            found_count[0] += 1
            name = obj.get("name") or obj.get("display_name") or obj.get("productName")
            print(f"\n  PRODUCT FOUND at {path}:")
            print(f"    name = {name}")
            print(f"    keys = {sorted(obj.keys())}")
            # Show all values for inventory scanning
            for k, v in sorted(obj.items()):
                if not isinstance(v, (dict, list)):
                    print(f"    {k} = {repr(v)[:120]}")
                elif isinstance(v, dict):
                    print(f"    {k} = {{...}} ({len(v)} keys: {list(v.keys())[:10]})")
                elif isinstance(v, list):
                    print(f"    {k} = [...] (len={len(v)})")
            return
        for key, val in obj.items():
            _find_products(val, f"{path}.{key}", depth + 1, found_count)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:10]):
            _find_products(item, f"{path}[{i}]", depth + 1, found_count)


if __name__ == "__main__":
    asyncio.run(run())
