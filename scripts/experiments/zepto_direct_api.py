#!/usr/bin/env python3
"""Directly call Zepto's BFF gateway search API from within the browser context.

The browser has session cookies from navigating to zepto.com.
We use browser_evaluate to make a direct fetch() call to the search endpoint
and dump the complete response.
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


def _parse_evaluate_result(result) -> str:
    """Extract the string value from a browser_evaluate result."""
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


async def main():
    server = _build_server()
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                # Step 1: Navigate to Zepto to establish session cookies
                logger.info("Navigating to Zepto search page...")
                await session.call_tool("browser_navigate", {
                    "url": "https://www.zepto.com/search?query=milk"
                })
                await session.call_tool("browser_wait_for", {"time": 5000})

                # Step 2: Call the BFF gateway search API directly
                # The browser has the cookies from navigating to zepto.com
                logger.info("Calling BFF gateway search API directly...")
                result = await session.call_tool("browser_evaluate", {"function": """() => {
                    return fetch('https://bff-gateway.zepto.com/user-search-service/api/v3/search', {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                            'Origin': 'https://www.zepto.com',
                            'Referer': 'https://www.zepto.com/',
                        },
                        body: JSON.stringify({
                            query: 'milk',
                            pageNumber: 0,
                            mode: 'AUTOSUGGEST',
                        })
                    })
                    .then(r => r.text())
                    .then(text => text.substring(0, 15000))
                    .catch(e => 'FETCH_ERROR: ' + e.message);
                }"""})

                raw = _parse_evaluate_result(result)

                if raw.startswith('FETCH_ERROR'):
                    logger.error("Direct API call failed: %s", raw)
                    # Try different body formats
                    for body_variant in [
                        '{"query":"milk"}',
                        '{"search_query":"milk","page":0}',
                        '{"q":"milk","page_number":0,"page_size":20}',
                    ]:
                        logger.info("Trying body: %s", body_variant)
                        result = await session.call_tool("browser_evaluate", {"function": f"""() => {{
                            return fetch('https://bff-gateway.zepto.com/user-search-service/api/v3/search', {{
                                method: 'POST',
                                credentials: 'include',
                                headers: {{
                                    'Content-Type': 'application/json',
                                    'Accept': 'application/json',
                                }},
                                body: '{body_variant}'
                            }})
                            .then(r => r.status + ' ' + r.text().then(t => t.substring(0, 5000)))
                            .catch(e => 'ERROR: ' + e.message);
                        }}"""})
                        raw2 = _parse_evaluate_result(result)
                        print(f"  Variant result: {raw2[:500]}")
                else:
                    # Parse and analyze the response
                    print(f"\n{'='*80}")
                    print(f"  ZEPTO BFF GATEWAY SEARCH API RESPONSE")
                    print(f"{'='*80}")

                    try:
                        data = json.loads(raw)
                        # Dump structure
                        print(f"\n  Response type: {type(data).__name__}")
                        if isinstance(data, dict):
                            print(f"  Top-level keys: {sorted(data.keys())}")

                        # Pretty print first 15KB
                        pretty = json.dumps(data, indent=2)
                        if len(pretty) > 15000:
                            pretty = pretty[:15000] + "\n... (truncated)"
                        print(f"\n{pretty}")

                        # Save to file
                        with open("data/zepto_bff_response.json", "w") as f:
                            json.dump(data, f, indent=2)
                        print(f"\n  Saved to data/zepto_bff_response.json")
                    except json.JSONDecodeError:
                        print(f"  Raw text (not JSON):\n{raw[:5000]}")

                # Step 3: Also try fetching one product RSC URL to see product detail data
                logger.info("Fetching a product RSC URL...")
                # Get the list of product RSC URLs from network requests
                net_result = await session.call_tool("browser_network_requests", {})
                net_text = _result_text(net_result)

                # Find product URLs
                product_urls = re.findall(r'https://www\.zepto\.com/pn/[^\s]+\?_rsc=[^\s]+', net_text)
                if product_urls:
                    purl = product_urls[0]
                    logger.info("Fetching product RSC: %s", purl[:80])
                    result = await session.call_tool("browser_evaluate", {"function": f"""() => {{
                        return fetch('{purl}', {{credentials: 'include'}})
                            .then(r => r.text())
                            .then(text => text.substring(0, 10000))
                            .catch(e => 'ERROR: ' + e.message);
                    }}"""})
                    rsc_text = _parse_evaluate_result(result)
                    print(f"\n{'='*80}")
                    print(f"  PRODUCT RSC RESPONSE (first product)")
                    print(f"{'='*80}")
                    print(rsc_text[:5000])

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
