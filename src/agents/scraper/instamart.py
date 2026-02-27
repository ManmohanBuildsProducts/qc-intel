"""Swiggy Instamart scraper — deterministic Playwright-based product extraction."""

import logging

from mcp import ClientSession

from src.models.product import Platform

from .base import BaseScraper

logger = logging.getLogger(__name__)


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
        category_slug = category.lower().replace(" & ", "-").replace(" ", "-")
        return f"https://www.swiggy.com/instamart/search?custom_back=true&query={category_slug.replace('-', '+')}"

    async def _run_scrape(self, session: ClientSession, pincode: str, category: str) -> list[dict]:
        """Scrape Instamart: navigate, set location, extract products."""
        # Step 1: Navigate to Instamart homepage
        logger.info("[instamart] Navigating to Instamart...")
        await self._navigate(session, "https://www.swiggy.com/instamart")
        await self._wait(session)

        # Step 2: Try to set location
        logger.info("[instamart] Setting location for pincode %s...", pincode)
        await self._evaluate(session, (
            f'() => {{ '
            f'localStorage.setItem("imart_pincode", "{pincode}"); '
            f'localStorage.setItem("userPincode", "{pincode}"); '
            f'return "pincode set"; }}'
        ))

        # Step 3: Navigate to search for this category
        search_query = category.replace(" & ", " ").replace("  ", " ")
        url = f"https://www.swiggy.com/instamart/search?custom_back=true&query={search_query.replace(' ', '+')}"
        logger.info("[instamart] Navigating to %s", url)
        await self._navigate(session, url)
        await self._wait(session)
        await self._evaluate(session, '() => { window.scrollTo(0, 1000); return "scrolled"; }')
        await self._wait(session)

        # Step 4: Extract products from DOM
        logger.info("[instamart] Extracting products...")
        result = await self._evaluate(session, """() => {
            const products = [];
            // Swiggy Instamart product cards
            const sel = '[data-testid*="product"],'
                + ' [class*="ProductCard"], [class*="product-card"],'
                + ' [class*="ItemCard"]';
            const cards = document.querySelectorAll(sel);
            for (const card of cards) {
                const ne = card.querySelector(
                    '[class*="name"], [class*="Name"],'
                    + ' [class*="title"], [class*="Title"], h4, h5');
                const name = ne?.textContent?.trim() || '';
                const pe = card.querySelector(
                    '[class*="price"], [class*="Price"],'
                    + ' [class*="amount"]');
                const priceText = pe?.textContent?.trim() || '0';
                const price = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                const img = card.querySelector('img')?.src || null;
                const sizeEl = card.querySelector(
                    '[class*="size"], [class*="weight"],'
                    + ' [class*="quantity"], [class*="pack"]');
                const packSize = sizeEl?.textContent?.trim() || null;
                if (name && name.length > 2) {
                    products.push({
                        id: 'im-' + (products.length + 1),
                        name: name,
                        brand: null,
                        category: null,
                        subcategory: null,
                        packSize: packSize,
                        price: price,
                        totalPrice: price,
                        inStock: true,
                        maxSelectableQuantity: 5,
                        images: img ? [img] : []
                    });
                }
            }
            return JSON.stringify(products);
        }""")

        items = self._parse_json_from_evaluate(result)

        # Fallback: snapshot extraction
        if not items or len(items) == 0:
            logger.info("[instamart] DOM scraping returned 0, trying snapshot...")
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
