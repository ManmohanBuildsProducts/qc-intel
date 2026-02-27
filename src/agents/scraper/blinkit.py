"""Blinkit scraper — deterministic Playwright-based product extraction."""

import logging

from mcp import ClientSession

from src.config.settings import get_pincode_location
from src.models.product import Platform

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Blinkit category slugs → internal L2 category IDs
BLINKIT_CATEGORIES = {
    "Dairy & Bread": "/cn/dairy-bread-eggs/cid/16/948",
    "Fruits & Vegetables": "/cn/fresh-vegetables/cid/1487/1489",
    "Snacks & Munchies": "/cn/snacks-munchies/cid/1512/1514",
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
        category_path = BLINKIT_CATEGORIES.get(category)
        if category_path:
            return f"https://blinkit.com{category_path}?lat={lat}&lon={lng}"
        category_slug = category.lower().replace(" & ", "-").replace(" ", "-")
        return f"https://blinkit.com/cn/{category_slug}?lat={lat}&lon={lng}"

    async def _run_scrape(self, session: ClientSession, pincode: str, category: str) -> list[dict]:
        """Scrape Blinkit: set location cookies, navigate to category, extract products from DOM."""
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        # Step 1: Navigate to homepage to establish session
        logger.info("[blinkit] Navigating to homepage...")
        await self._navigate(session, "https://blinkit.com")
        await self._wait(session)

        # Step 2: Set location cookies
        logger.info("[blinkit] Setting location cookies for %s (%.4f, %.4f)", pincode, lat, lng)
        await self._evaluate(session, (
            f'() => {{ '
            f'document.cookie = "gr_1_lat={lat};path=/;max-age=86400"; '
            f'document.cookie = "gr_1_lon={lng};path=/;max-age=86400"; '
            f'document.cookie = "lat={lat};path=/;max-age=86400"; '
            f'document.cookie = "lon={lng};path=/;max-age=86400"; '
            f'return "cookies set"; }}'
        ))

        # Step 3: Navigate to the category page
        url = self.get_scrape_url(pincode, category)
        logger.info("[blinkit] Navigating to %s", url)
        await self._navigate(session, url)
        await self._wait(session)

        # Step 4: Scroll to load products and wait
        await self._evaluate(session, '() => { window.scrollTo(0, 1000); return "scrolled"; }')
        await self._wait(session)

        # Step 5: Extract product data from DOM
        logger.info("[blinkit] Extracting products from page...")
        result = await self._evaluate(session, """() => {
            const products = [];
            const sel = '[data-testid="plp-product"],'
                + ' .Product__UpdatedPlpProductContainer-sc-11dk8zk-0,'
                + ' div[class*="Product__"]';
            const cards = document.querySelectorAll(sel);
            if (cards.length === 0) {
                // Try alternative selectors
                const allDivs = document.querySelectorAll('div');
                for (const div of allDivs) {
                    const nameEl = div.querySelector('div[class*="name"], div[class*="Name"]');
                    const priceEl = div.querySelector('div[class*="price"], div[class*="Price"]');
                    if (nameEl && priceEl) {
                        const name = nameEl.textContent.trim();
                        const priceText = priceEl.textContent.trim();
                        const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                        if (name && name.length > 2 && price > 0) {
                            products.push({
                                id: products.length + 1,
                                name: name,
                                brand: null,
                                category: null,
                                subcategory: null,
                                unit: null,
                                price: price,
                                mrp: price,
                                available: true,
                                max_allowed_quantity: 5,
                                image_url: null
                            });
                        }
                    }
                    if (products.length >= 50) break;
                }
            } else {
                for (const card of cards) {
                    const name = card.querySelector('[class*="name"], [class*="Name"]')?.textContent?.trim() || '';
                    const pe = card.querySelector('[class*="price"], [class*="Price"]');
                    const priceText = pe?.textContent?.trim() || '0';
                    const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                    const img = card.querySelector('img')?.src || null;
                    if (name) {
                        products.push({
                            id: products.length + 1,
                            name: name,
                            brand: null,
                            category: null,
                            subcategory: null,
                            unit: null,
                            price: price,
                            mrp: price,
                            available: true,
                            max_allowed_quantity: 5,
                            image_url: img
                        });
                    }
                }
            }
            return JSON.stringify(products);
        }""")

        items = self._parse_json_from_evaluate(result)

        # If DOM scraping failed, try snapshot-based extraction
        if not items or len(items) == 0:
            logger.info("[blinkit] DOM scraping returned 0, trying snapshot extraction...")
            snapshot = await self._snapshot(session)
            items = self._extract_products_from_snapshot(snapshot, category)

        return items if isinstance(items, list) else []

    @staticmethod
    def _extract_products_from_snapshot(snapshot: str, category: str) -> list[dict]:
        """Extract product info from accessibility snapshot YAML text."""
        import re

        products = []
        # Look for product-like patterns: name followed by price (₹XX)
        lines = snapshot.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Match price pattern ₹XX or Rs XX
            price_match = re.search(r"[₹Rs.]\s*(\d+(?:\.\d+)?)", line)
            if price_match and i > 0:
                price = float(price_match.group(1))
                # Look back for a product name (text without price that's not a UI element)
                for j in range(max(0, i - 3), i):
                    prev = lines[j].strip()
                    # Skip UI chrome
                    skip = ["search", "login", "cart", "delivery", "ref=", "link", "button"]
                    if any(x in prev.lower() for x in skip):
                        continue
                    name_match = re.search(r":\s*(.+)", prev)
                    if name_match:
                        name = name_match.group(1).strip().strip('"')
                        if len(name) > 3 and not name.startswith("http"):
                            products.append({
                                "id": len(products) + 1,
                                "name": name,
                                "brand": None,
                                "category": category,
                                "subcategory": None,
                                "unit": None,
                                "price": price,
                                "mrp": price,
                                "available": True,
                                "max_allowed_quantity": 5,
                                "image_url": None,
                            })
                            break
            i += 1
        return products
