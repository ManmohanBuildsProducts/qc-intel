#!/usr/bin/env python3
"""Extract Zepto product data from Next.js hydration state.

Next.js SSR embeds server-fetched data in __NEXT_DATA__, RSC payloads, or
React hydration scripts. This extracts the raw product data from whatever
source is available, revealing ALL fields including any inventory data.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

LAT, LNG = 26.8607, 75.7633
PINCODE = "302020"

INV_KEYWORDS = {"inventory", "stock", "quantity", "available", "sellable",
                "count", "remaining", "supply", "max_order", "sold", "units",
                "max_qty", "cart_limit"}


def _script_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), "..", "src", "agents", "scraper", name)


def _build_server() -> StdioServerParameters:
    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    stealth = _script_path("stealth.js")
    if os.path.exists(stealth):
        args += ["--init-script", stealth]
    return StdioServerParameters(command="npx", args=args)


def _result_text(result) -> str:
    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text
    return text


def _parse_result_value(result) -> str:
    text = _result_text(result)
    match = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", text, re.DOTALL)
    if match:
        raw = match.group(1).strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
        return raw
    return text


def scan_for_inventory(obj, path="", depth=0, found=None):
    if found is None:
        found = []
    if depth > 12:
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_lower = k.lower().replace("-", "_")
            curr = f"{path}.{k}" if path else k
            if any(kw in k_lower for kw in INV_KEYWORDS):
                found.append((curr, v, type(v).__name__))
            if isinstance(v, (dict, list)):
                scan_for_inventory(v, curr, depth + 1, found)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):
            scan_for_inventory(item, f"{path}[{i}]", depth + 1, found)
    return found


async def main():
    server = _build_server()
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                # Navigate to search page
                logger.info("Navigating to Zepto search...")
                await session.call_tool("browser_navigate", {
                    "url": "https://www.zepto.com/search?query=milk"
                })
                await session.call_tool("browser_wait_for", {"time": 5000})

                # Strategy 1: __NEXT_DATA__
                logger.info("Extracting __NEXT_DATA__...")
                result = await session.call_tool("browser_evaluate", {"function": """() => {
                    const el = document.querySelector('#__NEXT_DATA__');
                    if (el) return el.textContent.substring(0, 30000);
                    return 'NOT_FOUND';
                }"""})
                next_data = _parse_result_value(result)
                if next_data != "NOT_FOUND":
                    print(f"\n  __NEXT_DATA__ found! ({len(next_data)} chars)")
                    try:
                        data = json.loads(next_data)
                        with open("data/zepto_next_data.json", "w") as f:
                            json.dump(data, f, indent=2)
                        inv = scan_for_inventory(data)
                        if inv:
                            print(f"\n  INVENTORY FIELDS FOUND ({len(inv)}):")
                            for path, val, vtype in inv[:20]:
                                print(f"    {path}: {repr(val)[:100]}  ({vtype})")
                        else:
                            print("  No inventory-related fields in __NEXT_DATA__")
                    except json.JSONDecodeError:
                        print(f"  Not valid JSON")
                else:
                    print("  __NEXT_DATA__ not found (app uses RSC)")

                # Strategy 2: RSC flight data (self.__next_f)
                logger.info("Looking for RSC flight data (self.__next_f)...")
                result = await session.call_tool("browser_evaluate", {"function": """() => {
                    if (self.__next_f) {
                        const items = self.__next_f.map(function(f) {
                            if (typeof f[1] === 'string' && f[1].length > 100) {
                                return f[1].substring(0, 8000);
                            }
                            return null;
                        }).filter(Boolean);
                        return JSON.stringify(items.slice(0, 10));
                    }
                    return '[]';
                }"""})
                rsc_raw = _parse_result_value(result)
                try:
                    rsc_items = json.loads(rsc_raw) if isinstance(rsc_raw, str) else []
                    print(f"\n  RSC flight data: {len(rsc_items)} chunks")
                    product_chunks = []
                    for i, chunk in enumerate(rsc_items):
                        has_product = any(kw in chunk.lower() for kw in ['product', 'mrp', 'discounted_price', 'inventory', 'stock', 'max_cart'])
                        if has_product:
                            product_chunks.append((i, chunk))
                            print(f"    Chunk {i}: PRODUCT DATA ({len(chunk)} chars)")
                        else:
                            print(f"    Chunk {i}: no product data ({len(chunk)} chars)")

                    # Dump product chunks and scan for inventory
                    for ci, chunk in product_chunks[:3]:
                        print(f"\n  === RSC Chunk {ci} ===")
                        # Try to find JSON objects in the chunk
                        # RSC format is like: 1:["$","div",null,...] or contains JSON blobs
                        json_blobs = re.findall(r'\{[^{}]{50,}\}', chunk)
                        for ji, blob in enumerate(json_blobs[:5]):
                            try:
                                parsed = json.loads(blob)
                                inv = scan_for_inventory(parsed)
                                if inv:
                                    print(f"    JSON blob {ji} — INVENTORY FIELDS:")
                                    for path, val, vtype in inv:
                                        print(f"      {path}: {repr(val)[:100]}  ({vtype})")
                                else:
                                    keys = list(parsed.keys()) if isinstance(parsed, dict) else "list"
                                    print(f"    JSON blob {ji} — keys: {str(keys)[:200]}")
                            except json.JSONDecodeError:
                                pass
                        # Also just show raw content for inspection
                        print(f"    Raw preview: {chunk[:1000]}")

                    # Save all product chunks to file
                    if product_chunks:
                        with open("data/zepto_rsc_product_chunks.json", "w") as f:
                            json.dump([c[1] for c in product_chunks], f, indent=2)
                        print(f"\n  Saved product chunks to data/zepto_rsc_product_chunks.json")

                except (json.JSONDecodeError, TypeError) as e:
                    print(f"  Could not parse RSC data: {e}")

                # Strategy 3: localStorage stores
                logger.info("Checking localStorage stores...")
                result = await session.call_tool("browser_evaluate", {"function": """() => {
                    var stores = {};
                    for (var i = 0; i < localStorage.length; i++) {
                        var key = localStorage.key(i);
                        if (key) {
                            var val = localStorage.getItem(key);
                            if (val && val.length > 50) {
                                stores[key] = val.substring(0, 2000);
                            }
                        }
                    }
                    return JSON.stringify(stores);
                }"""})
                stores_raw = _parse_result_value(result)
                try:
                    stores = json.loads(stores_raw) if isinstance(stores_raw, str) else {}
                    print(f"\n  localStorage: {len(stores)} keys with >50 chars")
                    for key in sorted(stores.keys()):
                        val = stores[key]
                        has_inv = any(kw in val.lower() for kw in INV_KEYWORDS)
                        print(f"    {key}: {len(val)} chars {'*** HAS INVENTORY KEYWORDS ***' if has_inv else ''}")
                        if has_inv:
                            print(f"      Preview: {val[:500]}")
                except (json.JSONDecodeError, TypeError):
                    print("  Could not parse localStorage")

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
