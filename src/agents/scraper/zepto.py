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
        return f"https://www.zeptonow.com/search?query={query.replace(' ', '+')}"

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
    ) -> list[dict]:
        """Scrape Zepto via search: navigate, search terms, extract."""
        # Step 1: Navigate to homepage
        logger.info("[zepto] Navigating to homepage...")
        await self._navigate(session, "https://www.zeptonow.com")
        await self._wait(session)

        # Step 2: Search for products in this category
        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_names: set[str] = set()

        for term in terms:
            url = f"https://www.zeptonow.com/search?query={term}"
            logger.info("[zepto] Searching: %s", url)
            await self._navigate(session, url)
            await self._wait(session)
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

        Products appear as link blocks with ``/url: /pn/...``.
        Inside each block: price (₹XX), name, and size generics.
        """
        products = []
        lines = snapshot.split("\n")
        i = 0
        while i < len(lines):
            # Find product URL marker
            if "/url: /pn/" in lines[i]:
                prices: list[float] = []
                name = None
                size = None

                # Scan next lines for product data
                for j in range(i + 1, min(i + 25, len(lines))):
                    line = lines[j].strip()
                    # Next product starts
                    if "/url: /pn/" in line:
                        break

                    # Price: generic [...]: ₹XX
                    pm = re.search(r"generic.*:\s*₹(\d+(?:\.\d+)?)\s*$", line)
                    if pm:
                        prices.append(float(pm.group(1)))
                        continue

                    # Size: contains unit keywords
                    sm = re.search(
                        r"generic.*:\s*"
                        r"(\d+\s*(?:pack|pcs?)?\s*\(.*?\)"
                        r"|\d+\s*(?:ml|ltr|l|gm|g|kg)\b)",
                        line, re.IGNORECASE,
                    )
                    if sm and not size:
                        size = sm.group(1) or sm.group(0)
                        # Clean up: extract just the value
                        m2 = re.search(r":\s*(.+)$", size)
                        if m2:
                            size = m2.group(1).strip()
                        continue

                    # Name: long generic text (not price, not UI)
                    nm = re.search(r"generic.*:\s*(.{8,})\s*$", line)
                    if nm and not name:
                        val = nm.group(1).strip().strip('"')
                        skip = ["₹", "(", "OFF", "ADD", "Cart",
                                "login", "Select", "Search", "Your"]
                        if not any(val.startswith(s) for s in skip):
                            name = val

                if name and prices:
                    price = prices[0]
                    mrp = prices[1] if len(prices) > 1 else price
                    products.append({
                        "product_id": f"z-{len(products) + 1}",
                        "name": name,
                        "brand_name": None,
                        "category": category,
                        "subcategory": None,
                        "unit_quantity": size,
                        "discounted_price": price,
                        "mrp": mrp,
                        "in_stock": True,
                        "max_cart_quantity": 5,
                        "images": [],
                    })
            i += 1
        return products
