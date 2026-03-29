"""Zepto fast scraper — XHR interception via fetch-patching init script.

Instead of parsing accessibility snapshots (~6 min/category), intercepts the
search API response directly from the patched fetch() call (~30s/category).
"""

import logging
import os
import sqlite3

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config.settings import get_pincode_location
from src.models.product import Platform, ScrapeRun, TimeOfDay

from .service import ScrapeService
from .zepto import CATEGORY_SEARCH_TERMS

logger = logging.getLogger(__name__)


def _xhr_intercept_path() -> str:
    return os.path.join(os.path.dirname(__file__), "xhr_intercept.js")


def _stealth_script_path() -> str:
    return os.path.join(os.path.dirname(__file__), "stealth.js")


class ZeptoFastScraper:
    """Fast Zepto scraper — intercepts search API responses via fetch patching."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.platform = Platform.ZEPTO
        self.conn = conn
        self.service = ScrapeService(conn)

    def _build_server(self) -> StdioServerParameters:
        args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
        stealth = _stealth_script_path()
        if os.path.exists(stealth):
            args += ["--init-script", stealth]
        xhr = _xhr_intercept_path()
        if os.path.exists(xhr):
            args += ["--init-script", xhr]
        return StdioServerParameters(command="npx", args=args)

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Scrape Zepto using XHR interception."""
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        items = await self._scrape_with_xhr(pincode, category, lat, lng)

        if not items:
            from src.models.exceptions import ScrapeError

            raise ScrapeError("zepto", "No products found via XHR interception")

        logger.info("[zepto-fast] Scraped %d products for %s/%s", len(items), pincode, category)
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
                        await session.call_tool("browser_close", {})
                    except Exception:
                        pass

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
        lat: float, lng: float,
    ) -> list[dict]:
        # Step 1: Navigate to homepage and set location
        logger.info("[zepto-fast] Setting location for %s (%.4f, %.4f)", pincode, lat, lng)
        await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
        await session.call_tool("browser_wait_for", {"time": 3000})

        # Set location via localStorage
        await session.call_tool("browser_evaluate", {"function": (
            f'() => {{ '
            f'const pos = {{state: {{userPosition: {{'
            f'lat: {lat}, lng: {lng}, pincode: "{pincode}", '
            f'city: "Jaipur", address: "Jaipur, Rajasthan"'
            f'}}, _hasHydrated: true}}, version: 0}}; '
            f'localStorage.setItem("user-position", JSON.stringify(pos)); '
            f'return "location set"; }}'
        )})

        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()

        for term in terms:
            # Clear previous captures
            await session.call_tool("browser_evaluate", {
                "function": "() => { window.__xhrCaptures = []; return 'cleared'; }",
            })

            # Navigate to search — this triggers the API call which gets intercepted
            url = f"https://www.zepto.com/search?query={term}"
            logger.info("[zepto-fast] Searching: %s", term)
            await session.call_tool("browser_navigate", {"url": url})
            await session.call_tool("browser_wait_for", {"time": 3000})

            # Retrieve intercepted API response
            result = await session.call_tool("browser_evaluate", {
                "function": "() => JSON.stringify(window.__xhrCaptures || [])",
            })
            captures = self._parse_result(result)

            if captures:
                for capture in captures:
                    body = capture.get("body", {})
                    items = self._extract_products(body, category)
                    for item in items:
                        pid = item.get("product_id", "")
                        name = item.get("name", "")
                        if not name:
                            continue
                        if pid and pid in seen_ids:
                            continue
                        if name in seen_names:
                            continue
                        if pid:
                            seen_ids.add(pid)
                        seen_names.add(name)
                        all_items.append(item)
                logger.info(
                    "[zepto-fast] term=%s captures=%d total=%d",
                    term, len(captures), len(all_items),
                )
            else:
                # Fallback: try snapshot extraction
                logger.info("[zepto-fast] No XHR captures for '%s', falling back to snapshot", term)
                from .zepto import ZeptoScraper

                snap_result = await session.call_tool("browser_snapshot", {})
                snap_text = self._result_text(snap_result)
                items = ZeptoScraper._extract_from_snapshot(snap_text, category)
                for item in items:
                    pid = item.get("product_id", "")
                    name = item.get("name", "")
                    if not name:
                        continue
                    if pid and pid in seen_ids:
                        continue
                    if name in seen_names:
                        continue
                    if pid:
                        seen_ids.add(pid)
                    seen_names.add(name)
                    all_items.append(item)
                logger.info(
                    "[zepto-fast] term=%s snapshot_items=%d total=%d",
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
    def _extract_products(data: dict, category: str) -> list[dict]:
        """Extract products from Zepto API response JSON."""
        products = []

        def walk(obj):
            if isinstance(obj, list):
                for item in obj:
                    walk(item)
            elif isinstance(obj, dict):
                # Look for product-like objects
                if "product_id" in obj or ("name" in obj and "mrp" in obj):
                    pid = obj.get("product_id") or obj.get("id", "")
                    name = obj.get("name") or obj.get("product_name", "")
                    if name and pid:
                        products.append({
                            "product_id": str(pid),
                            "name": name,
                            "brand_name": obj.get("brand_name") or obj.get("brand"),
                            "category": category,
                            "subcategory": obj.get("subcategory") or obj.get("category"),
                            "unit_quantity": obj.get("unit_quantity") or obj.get("quantity"),
                            "discounted_price": obj.get("discounted_price") or obj.get("price", 0),
                            "mrp": obj.get("mrp", 0),
                            "in_stock": obj.get("in_stock", True),
                            "max_cart_quantity": obj.get("max_cart_quantity", 5),
                            "images": obj.get("images", []),
                        })
                # Check common container keys
                for key in ("items", "products", "data", "sections", "widgets"):
                    if key in obj:
                        walk(obj[key])

        walk(data)
        return products

    @staticmethod
    def _result_text(result) -> str:
        text = ""
        for content in result.content:
            if hasattr(content, "text"):
                text += content.text
        return text
