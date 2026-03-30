#!/usr/bin/env python3
"""Inspect what network requests Zepto makes during a search.

Uses browser_network_requests to list ALL requests, finding the actual API endpoint.
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

PINCODE = "302020"
LAT, LNG = 26.8607, 75.7633


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


async def main():
    server = _build_server()
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                # Navigate to Zepto
                logger.info("Navigating to Zepto...")
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

                # Search
                logger.info("Navigating to search...")
                await session.call_tool("browser_navigate", {"url": "https://www.zepto.com/search?query=milk"})
                await session.call_tool("browser_wait_for", {"time": 5000})

                # List ALL network requests
                logger.info("Listing network requests...")
                result = await session.call_tool("browser_network_requests", {})
                text = _result_text(result)

                print("\n" + "=" * 80)
                print("  ALL NETWORK REQUESTS")
                print("=" * 80)
                print(text[:10000])

                # Also check: what does __xhrCaptures have?
                xhr_result = await session.call_tool("browser_evaluate", {
                    "function": "() => JSON.stringify((window.__xhrCaptures || []).map(c => ({url: c.url, status: c.status})))",
                })
                print("\n" + "=" * 80)
                print("  XHR CAPTURES")
                print("=" * 80)
                print(_result_text(xhr_result)[:3000])

                # Check: is fetch still the original or patched?
                fetch_check = await session.call_tool("browser_evaluate", {
                    "function": "() => window.fetch.toString().substring(0, 200)",
                })
                print("\n" + "=" * 80)
                print("  FETCH FUNCTION")
                print("=" * 80)
                print(_result_text(fetch_check)[:1000])

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
