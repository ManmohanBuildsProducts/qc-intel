#!/usr/bin/env python3
"""Capture Zepto BFF response using page.waitForResponse via browser_run_code."""

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


def _stealth_path():
    return os.path.join(os.path.dirname(__file__), "..", "src", "agents", "scraper", "stealth.js")


def _result_text(result):
    return "".join(c.text for c in result.content if hasattr(c, "text"))


def _parse_val(result):
    text = _result_text(result)
    m = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", text, re.DOTALL)
    if m:
        raw = m.group(1).strip()
        if raw.startswith('"') and raw.endswith('"'):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
        return raw
    return text


def find_products(obj, depth=0):
    if depth > 10:
        return []
    found = []
    if isinstance(obj, dict):
        if "availableQuantity" in obj or "inventory_available" in obj:
            found.append(obj)
        for v in obj.values():
            found.extend(find_products(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj[:50]:
            found.extend(find_products(item, depth + 1))
    return found


# Playwright code to run — sets up response listener, navigates, captures BFF response
PLAYWRIGHT_CODE = (
    "async (page) => {"
    "  var responsePromise = page.waitForResponse("
    "    function(response) { return response.url().includes('bff-gateway') && response.url().includes('search'); },"
    "    { timeout: 15000 }"
    "  );"
    "  await page.goto('https://www.zepto.com/search?query=milk', { waitUntil: 'domcontentloaded' });"
    "  var response = await responsePromise;"
    "  var body = await response.json();"
    ""
    "  var products = [];"
    "  function walk(obj) {"
    "    if (!obj || typeof obj !== 'object') return;"
    "    if (Array.isArray(obj)) { obj.forEach(walk); return; }"
    "    if (obj.availableQuantity !== undefined && obj.product && obj.mrp !== undefined) {"
    "      products.push({"
    "        id: obj.id || obj.objectId,"
    "        name: (obj.product || {}).name,"
    "        brand: (obj.product || {}).brand,"
    "        mrp: obj.mrp,"
    "        price: obj.discountedSellingPrice,"
    "        availableQuantity: obj.availableQuantity,"
    "        allocatedQuantity: obj.allocatedQuantity,"
    "        outOfStock: obj.outOfStock,"
    "        maxAllowedQuantity: (obj.productVariant || {}).maxAllowedQuantity,"
    "        packSize: (obj.productVariant || {}).formattedPacksize"
    "      });"
    "    }"
    "    Object.values(obj).forEach(function(v) { if (v && typeof v === 'object') walk(v); });"
    "  }"
    "  walk(body);"
    ""
    "  return JSON.stringify({totalResponseBytes: JSON.stringify(body).length, productCount: products.length, products: products});"
    "}"
)


async def main():
    stealth = _stealth_path()
    args = [
        "@playwright/mcp@latest", "--browser", "firefox",
        "--headless", "--isolated", "--caps", "code-execution",
    ]
    if os.path.exists(stealth):
        args += ["--init-script", stealth]

    server = StdioServerParameters(command="npx", args=args)
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Set location
            logger.info("Setting up location...")
            await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
            await session.call_tool("browser_wait_for", {"time": 3000})
            await session.call_tool("browser_evaluate", {"function": (
                f'() => {{ '
                f'const pos = {{state: {{userPosition: {{'
                f'lat: {LAT}, lng: {LNG}, pincode: "{PINCODE}", '
                f'city: "Jaipur", address: "Jaipur, Rajasthan"'
                f'}}, _hasHydrated: true}}, version: 0}}; '
                f'localStorage.setItem("user-position", JSON.stringify(pos)); '
                f'return "ok"; }}'
            )})

            # Capture BFF response
            logger.info("Capturing BFF response via page.waitForResponse...")
            result = await session.call_tool("browser_run_code", {
                "code": PLAYWRIGHT_CODE,
            })

            raw = _parse_val(result)
            full_text = _result_text(result)

            # Check for errors
            if "Error" in full_text and len(raw) < 100:
                logger.error("browser_run_code failed: %s", full_text[:500])
                await session.call_tool("browser_close", {})
                return

            # Parse size|||json format
            if isinstance(raw, str) and "|||" in raw:
                size_str, json_str = raw.split("|||", 1)
                logger.info("Full response: %s chars, captured: %d chars", size_str, len(json_str))
                raw = json_str
            else:
                logger.info("Response: %d chars", len(raw))

            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                logger.error("Not JSON (truncated?): %s", str(raw)[:500])
                await session.call_tool("browser_close", {})
                return

            if isinstance(data, dict):
                print(f"\nTop keys: {list(data.keys())[:15]}")
                with open("data/zepto_bff_captured.json", "w") as f:
                    json.dump(data, f, indent=2)
                print("Saved to data/zepto_bff_captured.json")

                products = find_products(data)
                print(f"\nProducts with inventory: {len(products)}")
                for p in products[:10]:
                    prod = p.get("product", {})
                    name = prod.get("name") or p.get("name", "?")
                    inv = p.get("availableQuantity", "?")
                    max_q = (p.get("productVariant") or {}).get("maxAllowedQuantity", "?")
                    mrp = p.get("mrp", "?")
                    oos = p.get("outOfStock", "?")
                    print(f"  {str(name)[:45]:45s} | inv={str(inv):>4s} | max={str(max_q):>3s} | mrp={mrp} | oos={oos}")
            else:
                print(f"Unexpected type: {type(data)}")

            await session.call_tool("browser_close", {})


if __name__ == "__main__":
    asyncio.run(main())
