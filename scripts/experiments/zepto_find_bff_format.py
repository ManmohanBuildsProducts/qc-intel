#!/usr/bin/env python3
"""Find the BFF API request format by inspecting Zepto's JS bundle."""

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


async def main():
    server = _build_server()
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            logger.info("Navigating to Zepto search...")
            await session.call_tool("browser_navigate", {
                "url": "https://www.zepto.com/search?query=milk"
            })
            await session.call_tool("browser_wait_for", {"time": 5000})

            # Intercept the NEXT BFF request by patching fetch to log request bodies
            logger.info("Patching fetch to capture request bodies...")
            await session.call_tool("browser_evaluate", {"function": """() => {
                window.__requestCaptures = [];
                var _prevFetch = window.fetch;
                window.fetch = function() {
                    var args = Array.from(arguments);
                    var url = typeof args[0] === 'string' ? args[0] : (args[0] && args[0].url ? args[0].url : '');
                    var opts = args[1] || {};
                    if (url.indexOf('bff-gateway') >= 0 || url.indexOf('search') >= 0) {
                        var body = opts.body || '';
                        if (args[0] instanceof Request) {
                            // Clone and read body
                            body = 'Request object - check headers';
                        }
                        window.__requestCaptures.push({
                            url: url,
                            method: opts.method || 'GET',
                            body: typeof body === 'string' ? body : JSON.stringify(body),
                            headers: JSON.stringify(opts.headers || {}),
                        });
                    }
                    return _prevFetch.apply(this, args);
                };
                return 'patched';
            }"""})

            # Trigger a new search by navigating
            logger.info("Triggering new search...")
            await session.call_tool("browser_navigate", {
                "url": "https://www.zepto.com/search?query=curd"
            })
            await session.call_tool("browser_wait_for", {"time": 5000})

            # Check captured requests
            result = await session.call_tool("browser_evaluate", {
                "function": "() => JSON.stringify(window.__requestCaptures || [])",
            })
            captures = _parse_result_value(result)
            try:
                reqs = json.loads(captures) if isinstance(captures, str) else []
            except json.JSONDecodeError:
                reqs = []

            print(f"\n=== CAPTURED {len(reqs)} REQUEST(S) ===")
            for r in reqs:
                print(f"\nURL: {r.get('url', '?')[:100]}")
                print(f"Method: {r.get('method', '?')}")
                print(f"Body: {r.get('body', '')[:1000]}")
                print(f"Headers: {r.get('headers', '')[:500]}")

            # Also: look at the page's JS source for BFF call format
            # Search loaded scripts for "bff-gateway" or "user-search"
            logger.info("\nSearching loaded scripts for BFF request format...")
            result = await session.call_tool("browser_evaluate", {"function": """() => {
                var scripts = performance.getEntriesByType('resource')
                    .filter(function(r) { return r.name.indexOf('_next/static/chunks') >= 0; })
                    .map(function(r) { return r.name; });
                return JSON.stringify(scripts.slice(0, 30));
            }"""})
            script_urls = _parse_result_value(result)
            try:
                urls = json.loads(script_urls) if isinstance(script_urls, str) else []
            except json.JSONDecodeError:
                urls = []
            print(f"\nLoaded {len(urls)} chunk scripts")

            # Try reading the serviceability cookie for store info
            result = await session.call_tool("browser_evaluate", {
                "function": "() => document.cookie",
            })
            cookie_str = _parse_result_value(result)
            for pair in (cookie_str or "").split(";"):
                pair = pair.strip()
                if pair.startswith("serviceability="):
                    decoded = pair.split("=", 1)[1]
                    try:
                        import urllib.parse
                        decoded = urllib.parse.unquote(decoded)
                        print(f"\nServiceability cookie (decoded): {decoded[:500]}")
                    except Exception:
                        print(f"\nServiceability cookie: {decoded[:500]}")

            try:
                await session.call_tool("browser_close", {})
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
