#!/usr/bin/env python3
"""Try calling Zepto BFF gateway search API directly via httpx.

1. Playwright navigates to Zepto, sets location (establishes session)
2. Extracts cookies + localStorage from the browser
3. Calls bff-gateway.zepto.com/user-search-service/api/v3/search via httpx
4. Tries different request body formats until one works
"""

import asyncio
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

LAT, LNG = 26.8607, 75.7633
PINCODE = "302020"
BFF_URL = "https://bff-gateway.zepto.com/user-search-service/api/v3/search"


def _script_path(name):
    return os.path.join(os.path.dirname(__file__), "..", "src", "agents", "scraper", name)


def _build_server():
    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    stealth = _script_path("stealth.js")
    if os.path.exists(stealth):
        args += ["--init-script", stealth]
    return StdioServerParameters(command="npx", args=args)


def _result_text(result):
    return "".join(c.text for c in result.content if hasattr(c, "text"))


def _parse_result_value(result):
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


def scan_inventory(obj, path="", depth=0):
    """Print any inventory-related fields found in nested data."""
    if depth > 8:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if "inventory" in kl or "available" in kl or "quantity" in kl or "stock" in kl:
                print(f"  FOUND: {path}.{k} = {v!r}"[:200])
            if isinstance(v, (dict, list)):
                scan_inventory(v, f"{path}.{k}", depth + 1)
    elif isinstance(obj, list) and obj:
        scan_inventory(obj[0], f"{path}[0]", depth + 1)


async def main():
    server = _build_server()
    cookies = {}
    local_storage = {}

    # Phase 1: Establish browser session
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            logger.info("Navigating to Zepto to establish session...")
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

            # Navigate to search to trigger store resolution
            await session.call_tool("browser_navigate", {
                "url": "https://www.zepto.com/search?query=milk"
            })
            await session.call_tool("browser_wait_for", {"time": 5000})

            # Extract cookies
            result = await session.call_tool("browser_evaluate", {
                "function": "() => document.cookie",
            })
            cookie_str = _parse_result_value(result)
            if cookie_str:
                for pair in cookie_str.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        cookies[k.strip()] = v.strip()

            # Extract ALL localStorage
            result = await session.call_tool("browser_evaluate", {"function": """() => {
                var stores = {};
                for (var i = 0; i < localStorage.length; i++) {
                    var key = localStorage.key(i);
                    if (key) stores[key] = localStorage.getItem(key);
                }
                return JSON.stringify(stores);
            }"""})
            ls_raw = _parse_result_value(result)
            try:
                local_storage = json.loads(ls_raw) if isinstance(ls_raw, str) else {}
            except json.JSONDecodeError:
                local_storage = {}

            # Look for store IDs and auth tokens
            print("\n=== SESSION STATE ===")
            print(f"Cookie keys: {sorted(cookies.keys())}")
            for key in sorted(local_storage.keys()):
                val = local_storage[key]
                if len(val) > 20:
                    print(f"localStorage[{key}]: {val[:200]}")

            try:
                await session.call_tool("browser_close", {})
            except Exception:
                pass

    # Phase 2: Call BFF API directly
    logger.info("\n=== CALLING BFF API DIRECTLY ===")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.zepto.com",
        "Referer": "https://www.zepto.com/search?query=milk",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }

    # Add any auth-looking cookies as headers too
    for k, v in cookies.items():
        if "token" in k.lower() or "auth" in k.lower() or "session" in k.lower():
            headers[f"X-Cookie-{k}"] = v

    body_variants = [
        {"query": "milk", "pageNumber": 0, "mode": "AUTOSUGGEST"},
        {"query": "milk", "page_number": 0, "page_size": 20},
        {"query": "milk"},
        {"searchQuery": "milk", "pageNumber": 0},
        {"query": "milk", "pageNumber": 0, "mode": "AUTOSUGGEST", "pageSize": 20},
    ]

    async with httpx.AsyncClient(timeout=15) as client:
        for i, body in enumerate(body_variants):
            try:
                resp = await client.post(BFF_URL, json=body, headers=headers, cookies=cookies)
                status = resp.status_code
                text = resp.text[:1000]
                print(f"\nVariant {i}: {json.dumps(body)}")
                print(f"  Status: {status}")

                if status == 200:
                    try:
                        data = resp.json()
                        if isinstance(data, dict):
                            print(f"  Top keys: {list(data.keys())[:10]}")
                            scan_inventory(data)
                            with open("data/zepto_bff_direct.json", "w") as f:
                                json.dump(data, f, indent=2)
                            print(f"  SAVED to data/zepto_bff_direct.json")
                            return  # Success!
                    except json.JSONDecodeError:
                        print(f"  Not JSON: {text[:300]}")
                elif status == 400:
                    print(f"  Bad request: {text[:300]}")
                elif status == 403:
                    print(f"  Forbidden: {text[:300]}")
                else:
                    print(f"  Response: {text[:300]}")
            except Exception as e:
                print(f"\nVariant {i}: ERROR {e}")

    print("\n=== No variant worked. Need to reverse-engineer the request format. ===")


if __name__ == "__main__":
    asyncio.run(main())
