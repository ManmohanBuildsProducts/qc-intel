"""Zepto scraper — deterministic Playwright-based product extraction."""

import logging
import re

from mcp import ClientSession

from src.models.product import Platform

from .base import BaseScraper

logger = logging.getLogger(__name__)

CATEGORY_SEARCH_TERMS = {
    "Dairy & Bread": ["milk", "curd", "bread", "butter", "cheese", "paneer"],
    "Fruits & Vegetables": ["vegetables", "fruits", "onion", "potato", "tomato"],
    "Snacks & Munchies": ["chips", "namkeen", "biscuits", "cookies", "snacks"],
}


class ZeptoScraper(BaseScraper):
    """Scraper for Zepto quick commerce platform."""

    def __init__(self, conn):
        super().__init__(Platform.ZEPTO, conn)

    def get_system_prompt(self) -> str:
        return (
            "You are a web scraping agent for Zepto (zepto.co). "
            "Your job is to extract product data from Zepto's API responses.\n\n"
            "Instructions:\n"
            "1. Navigate to the provided Zepto URL\n"
            "2. Zepto requires a store_id to be set first — this comes from the location/pincode selection\n"
            "3. Monitor network requests for API calls to /api/v3/search or /api/v4/catalog endpoints\n"
            "4. The store_id is typically set via a location selection API call\n"
            "5. Extract the products array from the API response JSON\n"
            "6. Return ONLY the raw JSON array of product objects\n\n"
            "Expected product fields: product_id, name, brand_name, category, subcategory, "
            "unit_quantity, discounted_price, mrp, in_stock, max_cart_quantity, images"
        )

    def get_scrape_url(self, pincode: str, category: str) -> str:
        query = category.lower().replace(" & ", " ")
        return f"https://www.zepto.com/search?query={query.replace(' ', '+')}"

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
    ) -> list[dict]:
        """Scrape Zepto via search: navigate, set location, click to load, extract."""
        # Step 1: Navigate to homepage and set Gurugram location
        logger.info("[zepto] Navigating to homepage...")
        await self._navigate(session, "https://www.zepto.com")
        await self._wait(session)
        await self._evaluate(session, (
            '() => { '
            'const pos = {state: {userPosition: {'
            'lat: 28.4595, lng: 77.0266, pincode: "122001", '
            'city: "Gurugram", address: "Gurugram, Haryana"'
            '}, _hasHydrated: true}, version: 0}; '
            'localStorage.setItem("user-position", JSON.stringify(pos)); '
            'return "location set"; }'
        ))

        # Step 2: Search for products in this category
        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_names: set[str] = set()
        location_clicked = False

        for term in terms:
            url = f"https://www.zepto.com/search?query={term}"
            logger.info("[zepto] Searching: %s", url)
            await self._navigate(session, url)
            await self._wait(session)
            # First search: click "Select Location" to trigger product loading
            if not location_clicked:
                snap = await self._snapshot(session)
                if "Select Location" in snap:
                    logger.info("[zepto] Clicking Select Location to load products")
                    try:
                        await session.call_tool(
                            "browser_click",
                            {"element": "Select Location button", "ref": ""},
                        )
                        location_clicked = True
                        await self._wait(session)
                    except Exception as e:
                        logger.warning("[zepto] Could not click Select Location: %s", e)
            await self._evaluate(
                session,
                '() => { window.scrollTo(0, 1000); return "scrolled"; }',
            )
            await self._wait(session)

            snapshot = await self._snapshot(session)
            items = self._extract_from_snapshot(snapshot, category)
            for item in items:
                name = item.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    item["product_id"] = f"z-{len(all_items) + 1}"
                    all_items.append(item)

            logger.info(
                "[zepto] term=%s found=%d total=%d",
                term, len(items), len(all_items),
            )

        return all_items

    @staticmethod
    def _extract_from_snapshot(
        snapshot: str, category: str,
    ) -> list[dict]:
        """Extract products from Zepto accessibility snapshot.

        Products appear as link elements with text:
        ``"NAME ADD [ad?] ₹price [₹mrp] [₹X OFF] NAME size rating (reviews)"``
        followed by ``/url: /pn/<slug>/pvid/<uuid>``
        """
        products = []
        lines = snapshot.split("\n")

        for i, line in enumerate(lines):
            # Find product URL lines
            if "/url: /pn/" not in line:
                continue

            # Extract product_id (pvid)
            pvid_m = re.search(r"/pvid/([a-f0-9-]+)", line)
            product_id = pvid_m.group(1) if pvid_m else f"z-{len(products) + 1}"

            # Find the link text in the preceding lines (within 3 lines)
            link_text = None
            for j in range(max(0, i - 3), i):
                m = re.search(r'link "(.+?)" \[ref=', lines[j])
                if m and "ADD" in m.group(1) and "₹" in m.group(1):
                    link_text = m.group(1)
                    break
            if not link_text:
                continue

            # Remove ad image references (e.g. "P3 - Ad.png")
            text = re.sub(r"P\d+\s*-\s*Ad\.png\s*", "", link_text)

            # Extract name: everything before " ADD"
            name_m = re.match(r"^(.+?)\s+ADD\b", text)
            if not name_m:
                continue
            name = name_m.group(1).strip()

            # Extract all ₹XX values; filter out "₹X OFF" discount amounts
            # Remove "₹X OFF" to avoid counting them as prices
            text_no_off = re.sub(r"₹\d+(?:\.\d+)?\s+OFF", "", text)
            prices = [float(p) for p in re.findall(r"₹(\d+(?:\.\d+)?)", text_no_off)]
            if not prices:
                continue
            discounted = prices[0]
            mrp = prices[1] if len(prices) > 1 else discounted

            # Extract size: "N pack (X ml/g/L)" or "N pc (X ml)" patterns
            size_m = re.search(
                r"(\d+\s*(?:pack|pc|pcs|pieces?)\s*\([^)]+\)"
                r"|\d+\s*(?:ml|g|kg|l|ltr)\b)",
                text, re.IGNORECASE,
            )
            size = size_m.group(0).strip() if size_m else None

            products.append({
                "product_id": product_id,
                "name": name,
                "brand_name": None,
                "category": category,
                "subcategory": None,
                "unit_quantity": size,
                "discounted_price": discounted,
                "mrp": mrp,
                "in_stock": True,
                "max_cart_quantity": 5,
                "images": [],
            })

        return products
