"""Zepto scraper — deterministic Playwright-based product extraction."""

import logging

from mcp import ClientSession

from src.models.product import Platform

from .base import BaseScraper

logger = logging.getLogger(__name__)


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
        category_slug = category.lower().replace(" & ", "-").replace(" ", "-")
        return f"https://www.zeptonow.com/search?query={category_slug.replace('-', '+')}"

    async def _run_scrape(self, session: ClientSession, pincode: str, category: str) -> list[dict]:
        """Scrape Zepto: navigate, set location, extract products."""
        # Step 1: Navigate to Zepto homepage
        logger.info("[zepto] Navigating to homepage...")
        await self._navigate(session, "https://www.zeptonow.com")
        await self._wait(session)

        # Step 2: Set pincode via local storage / cookies
        logger.info("[zepto] Setting pincode %s...", pincode)
        await self._evaluate(session, (
            f'() => {{ '
            f'localStorage.setItem("pincode", "{pincode}"); '
            f'localStorage.setItem("userPincode", "{pincode}"); '
            f'return "pincode set"; }}'
        ))

        # Step 3: Navigate to search for this category
        search_query = category.replace(" & ", " ").replace("  ", " ")
        url = f"https://www.zeptonow.com/search?query={search_query.replace(' ', '+')}"
        logger.info("[zepto] Navigating to %s", url)
        await self._navigate(session, url)
        await self._wait(session)
        await self._evaluate(session, '() => { window.scrollTo(0, 1000); return "scrolled"; }')
        await self._wait(session)

        # Step 4: Extract products from DOM
        logger.info("[zepto] Extracting products...")
        result = await self._evaluate(session, """() => {
            const products = [];
            // Try various Zepto product card selectors
            const sel = '[data-testid*="product"],'
                + ' [class*="ProductCard"], [class*="productCard"],'
                + ' a[href*="/product/"]';
            const cards = document.querySelectorAll(sel);
            for (const card of cards) {
                const ne = card.querySelector(
                    '[class*="name"], [class*="Name"],'
                    + ' [class*="title"], [class*="Title"], h5, h4');
                const name = ne?.textContent?.trim() || '';
                const pe = card.querySelector(
                    '[class*="price"], [class*="Price"],'
                    + ' [class*="amount"]');
                const priceText = pe?.textContent?.trim() || '0';
                const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                const img = card.querySelector('img')?.src || null;
                const weightEl = card.querySelector(
                    '[class*="weight"], [class*="quantity"],'
                    + ' [class*="unit"], [class*="variant"]');
                const unit = weightEl?.textContent?.trim() || null;
                if (name && name.length > 2) {
                    products.push({
                        product_id: 'z-' + (products.length + 1),
                        name: name,
                        brand_name: null,
                        category: null,
                        subcategory: null,
                        unit_quantity: unit,
                        discounted_price: price,
                        mrp: price,
                        in_stock: true,
                        max_cart_quantity: 5,
                        images: img ? [img] : []
                    });
                }
            }
            return JSON.stringify(products);
        }""")

        items = self._parse_json_from_evaluate(result)

        # Fallback: snapshot extraction
        if not items or len(items) == 0:
            logger.info("[zepto] DOM scraping returned 0, trying snapshot...")
            snapshot = await self._snapshot(session)
            items = self._extract_from_snapshot(snapshot, category)

        return items if isinstance(items, list) else []

    @staticmethod
    def _extract_from_snapshot(snapshot: str, category: str) -> list[dict]:
        """Extract products from accessibility snapshot."""
        import re

        products = []
        lines = snapshot.split("\n")
        for i, line in enumerate(lines):
            price_match = re.search(r"[₹Rs.]\s*(\d+(?:\.\d+)?)", line)
            if price_match:
                price = float(price_match.group(1))
                for j in range(max(0, i - 3), i):
                    prev = lines[j].strip()
                    if any(x in prev.lower() for x in ["search", "login", "cart", "delivery", "ref=", "link"]):
                        continue
                    name_match = re.search(r":\s*(.+)", prev)
                    if name_match:
                        name = name_match.group(1).strip().strip('"')
                        if len(name) > 3 and not name.startswith("http"):
                            products.append({
                                "product_id": f"z-{len(products) + 1}",
                                "name": name,
                                "brand_name": None,
                                "category": category,
                                "subcategory": None,
                                "unit_quantity": None,
                                "discounted_price": price,
                                "mrp": price,
                                "in_stock": True,
                                "max_cart_quantity": 5,
                                "images": [],
                            })
                            break
        return products
