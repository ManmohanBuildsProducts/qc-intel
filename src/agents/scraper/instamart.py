"""Swiggy Instamart scraper — deterministic Playwright-based product extraction."""

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

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
    ) -> list[dict]:
        """Scrape Instamart via search: navigate, search terms, extract."""
        # Step 1: Navigate to Swiggy homepage first (establish session)
        logger.info("[instamart] Navigating to Swiggy...")
        await self._navigate(session, "https://www.swiggy.com")
        await self._wait(session)

        # Step 2: Navigate to Instamart
        logger.info("[instamart] Navigating to Instamart...")
        await self._navigate(session, "https://www.swiggy.com/instamart")
        await self._wait(session)

        # Step 3: Search for products in this category
        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_names: set[str] = set()

        for term in terms:
            url = (
                f"https://www.swiggy.com/instamart/search"
                f"?custom_back=true&query={term}"
            )
            logger.info("[instamart] Searching: %s", url)
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
                    item["id"] = f"im-{len(all_items) + 1}"
                    all_items.append(item)

            logger.info(
                "[instamart] term=%s found=%d total=%d",
                term, len(items), len(all_items),
            )

        return all_items

    @staticmethod
    def _extract_from_snapshot(
        snapshot: str, category: str,
    ) -> list[dict]:
        """Extract products from Instamart accessibility snapshot.

        Scans for price patterns (₹XX) and nearby product names.
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
