"""Blinkit fast scraper — direct API calls via httpx, no browser per search term.

Uses one Playwright session to establish cookies, then calls /v1/layout/search
directly via httpx for all search terms. ~10x faster than browser-per-term approach.
"""

import logging
import sqlite3

import httpx
from mcp import ClientSession, StdioServerParameters

from src.config.settings import get_pincode_location
from src.models.product import Platform, ScrapeRun, TimeOfDay

from .blinkit import CATEGORY_SEARCH_TERMS
from .service import ScrapeService

logger = logging.getLogger(__name__)


class BlinkitFastScraper:
    """Fast Blinkit scraper — one browser session for cookies, then httpx API calls."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.platform = Platform.BLINKIT
        self.conn = conn
        self.service = ScrapeService(conn)

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Scrape Blinkit using direct API calls."""
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        # Step 1: Get session cookies from one browser visit
        cookies = await self._get_cookies(lat, lng)
        if not cookies:
            from src.models.exceptions import ScrapeError
            raise ScrapeError("blinkit", "Failed to obtain session cookies")

        # Step 2: Call API directly via httpx for each search term
        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_ids: set = set()

        async with httpx.AsyncClient(
            base_url="https://blinkit.com",
            cookies=cookies,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "lat": str(lat),
                "lon": str(lng),
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            timeout=15.0,
        ) as client:
            for term in terms:
                url_term = term.replace(" ", "+")
                try:
                    resp = await client.post(
                        f"/v1/layout/search?q={url_term}&search_type=type_to_search",
                        content="{}",
                    )
                    if resp.status_code != 200:
                        logger.warning("[blinkit-fast] API %d for term=%s", resp.status_code, term)
                        continue

                    data = resp.json()
                    items = self._walk_products(data)
                    new_count = 0
                    for item in items:
                        pid = item.get("id") or item.get("name", "")
                        if pid and pid not in seen_ids:
                            seen_ids.add(pid)
                            all_items.append(item)
                            new_count += 1
                    logger.info(
                        "[blinkit-fast] term=%s found=%d new=%d total=%d",
                        term, len(items), new_count, len(all_items),
                    )
                except Exception as e:
                    logger.warning("[blinkit-fast] Error for term=%s: %s", term, e)

        if not all_items:
            from src.models.exceptions import ScrapeError
            raise ScrapeError("blinkit", "No products found via direct API")

        logger.info("[blinkit-fast] Scraped %d products for %s/%s", len(all_items), pincode, category)
        return self.service.process_scrape_results(all_items, self.platform, pincode, category, time_of_day)

    async def _get_cookies(self, lat: float, lng: float) -> dict[str, str] | None:
        """Open one Chromium session to Blinkit, extract session cookies.

        Uses Chromium (not Firefox) to avoid profile lock conflicts when
        running in parallel with Zepto/Instamart scrapers.
        """
        import os

        from mcp.client.stdio import stdio_client

        from .base import _get_proxy_url, _stealth_script_path

        args = ["@playwright/mcp@latest", "--browser", "chromium", "--headless"]
        stealth_path = _stealth_script_path()
        if os.path.exists(stealth_path):
            args += ["--init-script", stealth_path]
        proxy_url = _get_proxy_url(self.platform)
        if proxy_url:
            args += ["--proxy-server", proxy_url]
        server = StdioServerParameters(command="npx", args=args)

        try:
            async with stdio_client(server) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    try:
                        url = f"https://blinkit.com/s/?q=milk&lat={lat}&lon={lng}"
                        await session.call_tool("browser_navigate", {"url": url})
                        await session.call_tool("browser_wait_for", {"time": 3000})

                        # Extract cookies via JS
                        result = await session.call_tool("browser_evaluate", {
                            "function": "() => document.cookie",
                        })
                        cookie_str = ""
                        for content in result.content:
                            if hasattr(content, "text"):
                                cookie_str += content.text

                        # Parse "### Result\nvalue" format
                        import re
                        match = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", cookie_str, re.DOTALL)
                        if match:
                            cookie_str = match.group(1).strip().strip('"')

                        cookies = {}
                        for pair in cookie_str.split(";"):
                            pair = pair.strip()
                            if "=" in pair:
                                k, v = pair.split("=", 1)
                                cookies[k.strip()] = v.strip()

                        logger.info("[blinkit-fast] Got %d cookies from browser session", len(cookies))
                        return cookies if cookies else None
                    finally:
                        try:
                            await session.call_tool("browser_close", {})
                        except Exception:
                            pass
        except Exception as e:
            logger.error("[blinkit-fast] Cookie extraction failed: %s", e)
            return None

    @staticmethod
    def _walk_products(data: dict) -> list[dict]:
        """Walk API response to extract cart_item product objects."""
        seen: set = set()
        products: list[dict] = []

        def walk(obj):
            if not obj or not isinstance(obj, dict | list):
                return
            if isinstance(obj, list):
                for item in obj:
                    walk(item)
                return
            if "cart_item" in obj and isinstance(obj["cart_item"], dict):
                item = obj["cart_item"]
                pid = item.get("product_id")
                if pid and pid not in seen:
                    seen.add(pid)
                    products.append({
                        "id": pid,
                        "name": item.get("product_name") or item.get("display_name", ""),
                        "brand": item.get("brand"),
                        "unit": item.get("unit"),
                        "price": item.get("price", 0),
                        "mrp": item.get("mrp"),
                        "inventory": item.get("inventory") if isinstance(item.get("inventory"), int) else None,
                        "image_url": item.get("image_url"),
                        "available": item.get("unavailable_quantity", 0) == 0,
                        "max_allowed_quantity": item.get("quantity", 0),
                    })
            for v in obj.values():
                if isinstance(v, dict | list):
                    walk(v)

        walk(data)
        return products
