"""Swiggy Instamart scraper — deterministic Playwright-based product extraction."""

import logging
import re

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.models.product import Platform, ScrapeRun, TimeOfDay

from .base import BaseScraper

# Use Chromium for Instamart — Swiggy's WAF blocks headless Firefox
INSTAMART_PLAYWRIGHT_SERVER = StdioServerParameters(
    command="npx",
    args=["@playwright/mcp@latest", "--browser", "chromium", "--headless"],
)

logger = logging.getLogger(__name__)

CATEGORY_SEARCH_TERMS = {
    "Dairy & Bread": ["milk", "curd", "bread", "butter", "cheese", "paneer"],
    "Fruits & Vegetables": ["vegetables", "fruits", "onion", "potato", "tomato"],
    "Snacks & Munchies": ["chips", "namkeen", "biscuits", "cookies", "snacks"],
}


class InstamartScraper(BaseScraper):
    """Scraper for Swiggy Instamart quick commerce platform."""

    def __init__(self, conn):
        super().__init__(Platform.INSTAMART, conn)

    def get_system_prompt(self) -> str:
        return (
            "You are a web scraping agent for Swiggy Instamart (instamart.swiggy.com). "
            "Your job is to extract product data from Instamart's API responses.\n\n"
            "Instructions:\n"
            "1. Navigate to the provided Instamart URL\n"
            "2. Instamart uses a tid (transaction ID) and cookie-based session for API auth\n"
            "3. Monitor network requests for API calls to /api/instamart/category or /api/instamart/search\n"
            "4. The tid is typically set during initial page load\n"
            "5. Extract the products array from the API response JSON (usually under data.widgets or similar)\n"
            "6. Return ONLY the raw JSON array of product objects\n\n"
            "Expected product fields: id, name, brand, category, subcategory, packSize, "
            "price, totalPrice, inStock, maxSelectableQuantity, images"
        )

    def get_scrape_url(self, pincode: str, category: str) -> str:
        query = category.lower().replace(" & ", " ")
        return (
            f"https://www.swiggy.com/instamart/search"
            f"?custom_back=true&query={query.replace(' ', '+')}"
        )

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Override to use Chromium — less detectable by Swiggy's WAF than Firefox."""
        async with stdio_client(INSTAMART_PLAYWRIGHT_SERVER) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    items = await self._run_scrape(session, pincode, category)
                finally:
                    try:
                        await session.call_tool("browser_close", {})
                    except Exception:
                        pass

        if not items:
            from src.models.exceptions import ScrapeError
            raise ScrapeError(self.platform.value, "Scraper returned no products")

        logger.info(
            "[%s] Scraped %d products for %s/%s",
            self.platform.value, len(items), pincode, category,
        )
        return self.service.process_scrape_results(
            items, self.platform, pincode, category, time_of_day,
        )

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
    ) -> list[dict]:
        """Scrape Instamart: establish session, call POST search API, fallback to snapshot."""
        # Step 1: Navigate to Swiggy homepage to establish session cookies
        logger.info("[instamart] Navigating to Swiggy homepage...")
        await self._navigate(session, "https://www.swiggy.com")
        await self._wait(session)

        # Step 2: Navigate to Instamart to pick up store/location context
        logger.info("[instamart] Navigating to Instamart...")
        await self._navigate(session, "https://www.swiggy.com/instamart")
        await self._wait(session)

        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_names: set[str] = set()

        for term in terms:
            logger.info("[instamart] Searching: %s", term)

            # Primary: call search API from within the page (session cookies sent automatically)
            js = (
                f'async () => {{ '
                f'try {{ '
                f'const r = await fetch('
                f'"/api/instamart/search/v2?offset=0&ageConsent=false'
                f'&pageType=INSTAMART_AUTO_SUGGEST_SEARCH_PAGE",'
                f'{{method:"POST",'
                f'headers:{{"Content-Type":"application/json",'
                f'"__fetch_req_type__":"data"}},'
                f'body:JSON.stringify({{query:"{term}",offset:0}})}}'
                f'); '
                f'const d = await r.json(); '
                f'return JSON.stringify(d); '
                f'}} catch(e) {{ return "ERROR:" + e.message; }} }}'
            )
            raw = await self._evaluate(session, js)
            parsed = self._parse_json_from_evaluate(raw)

            items: list[dict] = []
            if parsed and isinstance(parsed, dict):
                items = self._extract_from_api_response(parsed, category)
                logger.info("[instamart] API extraction: %d items for '%s'", len(items), term)

            if not items:
                # Fallback: navigate to search page and parse snapshot
                url = f"https://www.swiggy.com/instamart/search?custom_back=true&query={term}"
                await self._navigate(session, url)
                await self._wait(session)
                await self._evaluate(
                    session, '() => { window.scrollTo(0, 1000); return "scrolled"; }',
                )
                await self._wait(session)
                snapshot = await self._snapshot(session)
                items = self._extract_from_snapshot(snapshot, category)
                logger.info("[instamart] Snapshot fallback: %d items for '%s'", len(items), term)

            for item in items:
                name = item.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    item["id"] = f"im-{len(all_items) + 1}"
                    all_items.append(item)

            logger.info(
                "[instamart] term=%s found=%d total=%d",
                term, len(items), len(all_items),
            )

        return all_items

    @staticmethod
    def _extract_from_api_response(data: dict, category: str) -> list[dict]:
        """Extract products from Instamart search API JSON response.

        API returns: data.data.widgets[].data.products[].product
        """
        products = []
        widgets = data.get("data", {}).get("widgets", []) or []
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            raw_products = widget.get("data", {}).get("products", []) or []
            for p in raw_products:
                if not isinstance(p, dict):
                    continue
                prod = p.get("product", p)
                name = prod.get("name") or prod.get("display_name", "")
                if not name:
                    continue
                pricing = prod.get("pricing") or {}
                price = float(pricing.get("offer_price") or pricing.get("price") or 0)
                mrp = float(pricing.get("mrp") or price)
                cat_info = prod.get("category") or {}
                products.append({
                    "id": f"im-{len(products) + 1}",
                    "name": name,
                    "brand": prod.get("brand_name"),
                    "category": category,
                    "subcategory": cat_info.get("name") if isinstance(cat_info, dict) else None,
                    "packSize": prod.get("weight") or prod.get("quantity"),
                    "price": price,
                    "totalPrice": mrp,
                    "inStock": prod.get("in_stock", True),
                    "maxSelectableQuantity": prod.get("max_selectable_quantity", 5),
                    "images": [],
                })
        return products

    @staticmethod
    def _extract_from_snapshot(
        snapshot: str, category: str,
    ) -> list[dict]:
        """Fallback: extract products from Instamart accessibility snapshot.

        Scans for price patterns (₹XX) and nearby product name lines.
        """
        products = []
        lines = snapshot.split("\n")
        for i, line in enumerate(lines):
            price_match = re.search(r"₹\s*(\d+(?:\.\d+)?)", line)
            if not price_match:
                continue
            price = float(price_match.group(1))
            if price < 5 or price > 10000:
                continue

            # Look back for product name
            for j in range(max(0, i - 5), i):
                prev = lines[j].strip()
                skip = [
                    "search", "login", "cart", "delivery",
                    "link", "banner", "button", "heading",
                    "alert", "Try Again", "Something went",
                ]
                if any(x.lower() in prev.lower() for x in skip):
                    continue
                nm = re.search(r"generic.*:\s*(.{5,})\s*$", prev)
                if nm:
                    name = nm.group(1).strip().strip('"')
                    if (
                        len(name) > 3
                        and not name.startswith("http")
                        and not name.startswith("₹")
                        and "OFF" not in name
                    ):
                        products.append({
                            "id": f"im-{len(products) + 1}",
                            "name": name,
                            "brand": None,
                            "category": category,
                            "subcategory": None,
                            "packSize": None,
                            "price": price,
                            "totalPrice": price,
                            "inStock": True,
                            "maxSelectableQuantity": 5,
                            "images": [],
                        })
                        break
        return products
