"""Blinkit scraper — deterministic Playwright-based product extraction."""

import logging

from mcp import ClientSession

from src.config.settings import get_pincode_location
from src.models.product import Platform

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Search terms per category for broader product coverage
CATEGORY_SEARCH_TERMS = {
    "Dairy & Bread": ["milk", "curd", "bread", "butter", "cheese", "paneer"],
    "Fruits & Vegetables": ["vegetables", "fruits", "onion", "potato", "tomato"],
    "Snacks & Munchies": ["chips", "namkeen", "popcorn", "peanuts", "snacks"],
    "Beverages": ["cold drinks", "juice", "energy drink", "soda", "coconut water"],
    "Atta & Staples": ["atta", "rice", "dal", "maida", "besan"],
    "Chocolates & Sweets": ["chocolate", "candy", "sweets", "mithai"],
    "Bakery & Biscuits": ["biscuit", "cookies", "cake", "rusk"],
    "Tea & Coffee": ["tea", "coffee", "green tea", "kadak chai"],
    "Instant & Frozen Food": ["noodles", "frozen food", "instant mix", "pasta"],
}


class BlinkitScraper(BaseScraper):
    """Scraper for Blinkit quick commerce platform."""

    def __init__(self, conn):
        super().__init__(Platform.BLINKIT, conn)

    def get_system_prompt(self) -> str:
        return (
            "You are a web scraping agent for Blinkit (blinkit.com). "
            "Your job is to extract product data from Blinkit's API responses.\n\n"
            "Instructions:\n"
            "1. Navigate to the provided Blinkit URL\n"
            "2. Blinkit uses XHR requests to fetch product listings\n"
            "3. Monitor network requests for API calls to /v2/listing or /v6/listing endpoints\n"
            "4. The request headers must include lat and lon coordinates for the delivery location\n"
            "5. Extract the products array from the API response JSON\n"
            "6. Return ONLY the raw JSON array of product objects\n\n"
            "Expected product fields: id, name, brand, category, subcategory, unit, "
            "price, mrp, available, max_allowed_quantity, image_url"
        )

    def get_scrape_url(self, pincode: str, category: str) -> str:
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266
        query = category.lower().replace(" & ", " ")
        return f"https://blinkit.com/s/?q={query}&lat={lat}&lon={lng}"

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
    ) -> list[dict]:
        """Scrape Blinkit via search: set location, search terms, extract."""
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        # Step 1: Navigate to homepage to establish session
        logger.info("[blinkit] Navigating to homepage...")
        await self._navigate(session, "https://blinkit.com")
        await self._wait(session)

        # Step 2: Set location cookies
        logger.info("[blinkit] Setting location for %s (%.4f, %.4f)", pincode, lat, lng)
        await self._evaluate(session, (
            f'() => {{ '
            f'document.cookie = "gr_1_lat={lat};path=/;max-age=86400"; '
            f'document.cookie = "gr_1_lon={lng};path=/;max-age=86400"; '
            f'document.cookie = "lat={lat};path=/;max-age=86400"; '
            f'document.cookie = "lon={lng};path=/;max-age=86400"; '
            f'return "cookies set"; }}'
        ))

        # Step 3: Search for products in this category
        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_names: set[str] = set()

        for term in terms:
            url = f"https://blinkit.com/s/?q={term}&lat={lat}&lon={lng}"
            logger.info("[blinkit] Searching: %s", url)
            await self._navigate(session, url)
            await self._wait(session)
            await self._evaluate(
                session,
                '() => { window.scrollTo(0, 1000); return "scrolled"; }',
            )
            await self._wait(session)

            # Extract from snapshot (more reliable than DOM selectors)
            snapshot = await self._snapshot(session)
            items = self._extract_products_from_snapshot(
                snapshot, category,
            )
            for item in items:
                name = item.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    item["id"] = len(all_items) + 1
                    all_items.append(item)

            logger.info(
                "[blinkit] term=%s found=%d total=%d",
                term, len(items), len(all_items),
            )

        return all_items

    @staticmethod
    def _extract_products_from_snapshot(
        snapshot: str, category: str,
    ) -> list[dict]:
        """Extract products from accessibility snapshot.

        Blinkit search results appear as button elements with text like:
        ``"8 mins Mother Dairy Cow Milk 500 ml ₹30 ADD"``
        """
        import re

        # Pattern: "[N% OFF] N mins <name> <size> ₹<price> [₹<mrp>] ADD"
        pattern = re.compile(
            r'button\s+"(?:\d+%?\s+OFF\s+)?(\d+)\s+mins?\s+'  # optional % OFF + ETA
            r'(.+?)\s+'                     # product name
            r'([\d.,]+\s*(?:ml|ltr|l|gm|g|kg|pcs?|pack|can|bottle|pouch|sachet|box|jar|tin)\b'
            r'(?:\s*x\s*[\d.,]+\s*'
            r'(?:ml|ltr|l|gm|g|kg|pcs?|pack|can|bottle|pouch|sachet|box|jar|tin))?)\s+'  # size
            r'₹(\d+(?:\.\d+)?)'            # price
            r'(?:\s+₹(\d+(?:\.\d+)?))?'    # optional MRP
            r'\s+ADD"',
            re.IGNORECASE,
        )

        products = []
        for match in pattern.finditer(snapshot):
            name = match.group(2).strip()
            size = match.group(3).strip()
            price = float(match.group(4))
            mrp_str = match.group(5)
            mrp = float(mrp_str) if mrp_str else price

            products.append({
                "id": len(products) + 1,
                "name": name,
                "brand": None,
                "category": category,
                "subcategory": None,
                "unit": size,
                "price": price,
                "mrp": mrp,
                "available": True,
                "max_allowed_quantity": 5,
                "image_url": None,
            })

        return products
