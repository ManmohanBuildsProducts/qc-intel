"""Instamart fast scraper — XHR interception via fetch-patching init script.

Instead of parsing accessibility snapshots (~13 min/category), intercepts the
search API response directly from the patched fetch() call (~30s/category).
Uses the existing _extract_from_api_response() parser for the JSON structure.
"""

import logging
import os
import sqlite3

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config.settings import get_pincode_location
from src.models.product import Platform, ScrapeRun, TimeOfDay

from .instamart import CATEGORY_SEARCH_TERMS, InstamartScraper
from .service import ScrapeService

logger = logging.getLogger(__name__)


def _xhr_intercept_path() -> str:
    return os.path.join(os.path.dirname(__file__), "xhr_intercept.js")


def _stealth_script_path() -> str:
    return os.path.join(os.path.dirname(__file__), "stealth.js")


class InstamartFastScraper:
    """Fast Instamart scraper — intercepts search API responses via fetch patching."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.platform = Platform.INSTAMART
        self.conn = conn
        self.service = ScrapeService(conn)

    def _build_server(self) -> StdioServerParameters:
        args = ["@playwright/mcp@latest", "--browser", "chromium", "--headless"]
        stealth = _stealth_script_path()
        if os.path.exists(stealth):
            args += ["--init-script", stealth]
        xhr = _xhr_intercept_path()
        if os.path.exists(xhr):
            args += ["--init-script", xhr]
        return StdioServerParameters(command="npx", args=args)

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Scrape Instamart using XHR interception."""
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        items = await self._scrape_with_xhr(pincode, category, lat, lng)

        if not items:
            from src.models.exceptions import ScrapeError

            raise ScrapeError("instamart", "No products found via XHR interception")

        logger.info("[instamart-fast] Scraped %d products for %s/%s", len(items), pincode, category)
        return self.service.process_scrape_results(items, self.platform, pincode, category, time_of_day)

    async def _scrape_with_xhr(
        self, pincode: str, category: str, lat: float, lng: float,
    ) -> list[dict]:
        async with stdio_client(self._build_server()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    return await self._run_scrape(session, pincode, category, lat, lng)
                finally:
                    try:
                        import asyncio
                        async with asyncio.timeout(5):
                            await session.call_tool("browser_close", {})
                    except TimeoutError:
                        logger.warning("[instamart-fast] browser_close timed out")
                    except Exception as e:
                        logger.debug("[instamart-fast] browser_close failed: %s", e)

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
        lat: float, lng: float,
    ) -> list[dict]:
        # Step 1: Navigate to Swiggy homepage and set location cookies
        logger.info("[instamart-fast] Setting location for %s (%.4f, %.4f)", pincode, lat, lng)
        await session.call_tool("browser_navigate", {"url": "https://www.swiggy.com"})
        await session.call_tool("browser_wait_for", {"time": 3000})

        city = "Gurugram" if pincode.startswith("122") else "Jaipur"
        loc_json = (
            f'{{"address":"{city}","lat":{lat},"lng":{lng},'
            f'"id":"","annotation":"","name":"{city}"}}'
        )
        await session.call_tool("browser_evaluate", {"function": (
            f'() => {{ '
            f'const loc = encodeURIComponent(\'{loc_json}\'); '
            f'document.cookie = "userLocation=" + loc + ";path=/;max-age=86400"; '
            f'document.cookie = "_dl={lat};path=/;max-age=86400"; '
            f'return "location set"; }}'
        )})

        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_names: set[str] = set()

        for term in terms:
            # Clear previous captures
            await session.call_tool("browser_evaluate", {
                "function": "() => { window.__xhrCaptures = []; return 'cleared'; }",
            })

            # Navigate to search — triggers API call which gets intercepted
            url = f"https://www.swiggy.com/instamart/search?custom_back=true&query={term}"
            logger.info("[instamart-fast] Searching: %s", term)
            await session.call_tool("browser_navigate", {"url": url})
            await session.call_tool("browser_wait_for", {"time": 4000})

            # Retrieve intercepted API response
            result = await session.call_tool("browser_evaluate", {
                "function": "() => JSON.stringify(window.__xhrCaptures || [])",
            })
            captures = self._parse_result(result)

            if captures:
                # One-time dump: write first capture body for inventory field discovery
                _dump_path = os.path.join(
                    os.path.dirname(__file__), "..", "..", "..", "data", "instamart_raw_capture.json",
                )
                if not os.path.exists(_dump_path):
                    import json as _json
                    try:
                        with open(_dump_path, "w") as _f:
                            _json.dump(captures[0].get("body", {}), _f, indent=2, default=str)
                        logger.info("[instamart-fast] Dumped raw capture body to %s", _dump_path)
                    except Exception as _e:
                        logger.warning("[instamart-fast] Could not dump raw capture: %s", _e)

                for capture in captures:
                    body = capture.get("body", {})
                    # Use existing API response parser
                    items = InstamartScraper._extract_from_api_response(body, category)
                    for item in items:
                        name = item.get("name", "")
                        if name and name not in seen_names:
                            seen_names.add(name)
                            all_items.append(item)
                logger.info(
                    "[instamart-fast] term=%s captures=%d total=%d",
                    term, len(captures), len(all_items),
                )
            else:
                # Fallback: snapshot extraction
                logger.info("[instamart-fast] No XHR captures for '%s', falling back to snapshot", term)
                snap_result = await session.call_tool("browser_snapshot", {})
                snap_text = self._result_text(snap_result)
                items = InstamartScraper._extract_from_snapshot(snap_text, category)
                for item in items:
                    name = item.get("name", "")
                    if name and name not in seen_names:
                        seen_names.add(name)
                        all_items.append(item)
                logger.info(
                    "[instamart-fast] term=%s snapshot_items=%d total=%d",
                    term, len(items), len(all_items),
                )

        return all_items

    def _parse_result(self, result) -> list[dict]:
        """Parse XHR captures from browser_evaluate result."""
        import json
        import re

        text = self._result_text(result)
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

    @staticmethod
    def _result_text(result) -> str:
        text = ""
        for content in result.content:
            if hasattr(content, "text"):
                text += content.text
        return text
