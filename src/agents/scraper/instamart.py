"""Swiggy Instamart scraper — deterministic Playwright-based product extraction."""

import logging
import os
import re

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config.settings import get_pincode_location
from src.models.product import Platform

from .base import BaseScraper

logger = logging.getLogger(__name__)

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

    async def _scrape_once(self, pincode: str, category: str) -> list[dict]:
        """Override to use Chromium with stealth — less detectable by Swiggy's WAF."""
        from .base import _get_proxy_url, _stealth_script_path

        args = ["@playwright/mcp@latest", "--browser", "chromium", "--headless", "--isolated"]
        stealth_path = _stealth_script_path()
        if os.path.exists(stealth_path):
            args += ["--init-script", stealth_path]
        proxy_url = _get_proxy_url(self.platform)
        if proxy_url:
            args += ["--proxy-server", proxy_url]
        server = StdioServerParameters(command="npx", args=args)
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    return await self._run_scrape(session, pincode, category)
                finally:
                    try:
                        await session.call_tool("browser_close", {})
                    except Exception:
                        pass

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
    ) -> list[dict]:
        """Scrape Instamart via snapshot extraction from rendered search pages.

        Direct API calls (manual fetch) fail because Swiggy uses AWS WAF + SPA-internal
        auth that cannot be replicated via browser_evaluate. Instead, we navigate to
        search URLs and extract product data from the rendered accessibility snapshot.
        The page's own React app handles all auth automatically during navigation.
        """
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        # Step 1: Navigate to Swiggy homepage to establish session cookies + AWS WAF token
        logger.info("[instamart] Navigating to Swiggy homepage...")
        await self._navigate(session, "https://www.swiggy.com")
        await self._wait(session)

        # Step 2: Set location cookies on homepage (before navigating to Instamart)
        # Setting cookies on the Instamart page directly causes "Something went wrong"
        loc_json = (
            f'{{"address":"Gurugram","lat":{lat},"lng":{lng},'
            f'"id":"","annotation":"","name":"Gurugram"}}'
        )
        await self._evaluate(session, (
            f'() => {{ '
            f'const loc = encodeURIComponent(\'{loc_json}\'); '
            f'document.cookie = "userLocation=" + loc + ";path=/;max-age=86400"; '
            f'document.cookie = "_dl={lat};path=/;max-age=86400"; '
            f'return "location set"; }}'
        ))
        logger.info("[instamart] Location cookies set for (%.4f, %.4f)", lat, lng)

        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_names: set[str] = set()

        for term in terms:
            logger.info("[instamart] Searching: %s", term)
            items = await self._search_and_extract(session, term, category)

            for item in items:
                name = item.get("name", "")
                if name and name not in seen_names:
                    seen_names.add(name)
                    if not item.get("id") or str(item["id"]).startswith("im-"):
                        item["id"] = f"im-{len(all_items) + 1}"
                    all_items.append(item)

            logger.info(
                "[instamart] term=%s found=%d total=%d",
                term, len(items), len(all_items),
            )

        return all_items

    async def _search_and_extract(
        self, session: ClientSession, term: str, category: str,
    ) -> list[dict]:
        """Navigate to search URL, wait for products to render, extract via snapshot.

        Includes progressive scrolling and retry logic to handle slow rendering.
        """
        url = f"https://www.swiggy.com/instamart/search?custom_back=true&query={term}"
        await self._navigate(session, url)
        await self._wait(session)

        # Progressive scroll to trigger lazy loading and wait for render
        for scroll_y in (500, 1500, 3000):
            await self._evaluate(
                session,
                f'() => {{ window.scrollTo(0, {scroll_y}); return "scrolled"; }}',
            )
            await self._wait(session, timeout=2000)

        # Take snapshot and extract
        snapshot = await self._snapshot(session)
        items = self._extract_from_snapshot(snapshot, category)

        # Retry once with longer wait if no products found (page may be slow)
        if not items:
            logger.info("[instamart] No products on first attempt for '%s', retrying...", term)
            await self._wait(session, timeout=5000)
            # Scroll back to top and down again to re-trigger lazy loading
            await self._evaluate(session, '() => { window.scrollTo(0, 0); return "top"; }')
            await self._wait(session, timeout=1000)
            await self._evaluate(
                session, '() => { window.scrollTo(0, document.body.scrollHeight); return "bottom"; }',
            )
            await self._wait(session, timeout=3000)
            snapshot = await self._snapshot(session)
            items = self._extract_from_snapshot(snapshot, category)

        if items:
            logger.info("[instamart] Snapshot extraction: %d items for '%s'", len(items), term)
        else:
            logger.warning("[instamart] No products found for '%s' after retry", term)

        return items

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
                # Real product ID from API
                real_id = prod.get("id") or prod.get("product_id")
                # Image URL: try direct field, then images array
                images = prod.get("images") or []
                image_url = prod.get("image_url") or (images[0] if images else None)
                products.append({
                    "id": str(real_id) if real_id else f"im-{len(products) + 1}",
                    "name": name,
                    "brand": prod.get("brand_name"),
                    "category": category,
                    "subcategory": cat_info.get("name") if isinstance(cat_info, dict) else None,
                    "packSize": prod.get("weight") or prod.get("quantity"),
                    "price": price,
                    "totalPrice": mrp,
                    "inStock": prod.get("in_stock", True),
                    "maxSelectableQuantity": prod.get("max_selectable_quantity", 0),
                    "inventory_count": prod.get("available_quantity") or prod.get("inventory_count"),
                    "image_url": image_url,
                    "images": images,
                })
        return products

    @staticmethod
    def _extract_from_snapshot(
        snapshot: str, category: str,
    ) -> list[dict]:
        """Extract products from Instamart accessibility snapshot.

        Each product card has the structure (from Playwright snapshot):
          generic "Delivery in XX MINS" [ref=...]:
            generic [ref=...]: XX MINS
          generic [ref=...]: <Product Name>
          generic [ref=...]: <description>
          generic [ref=...]:
            text: <size>             ← e.g., "500 ml", "1 ltr"
            img [ref=...]            ← dropdown chevron
          generic [ref=...]: ₹ <price>
        """
        products = []
        lines = snapshot.split("\n")

        for i, line in enumerate(lines):
            if 'generic "Delivery in' not in line or "MINS" not in line:
                continue

            # Find product name: first valid generic line after the delivery marker
            # (skip the "XX MINS" sub-line, delivery-related text, short strings)
            name = None
            name_idx = -1
            for j in range(i + 1, min(i + 6, len(lines))):
                nm = re.search(r"generic\s*[^\n:]*:\s*(.{5,})\s*$", lines[j])
                if not nm:
                    continue
                candidate = nm.group(1).strip()
                if (
                    "MINS" not in candidate
                    and "Delivery" not in candidate
                    and not candidate.startswith("₹")
                    and not candidate.startswith("http")
                    and "OFF" not in candidate
                ):
                    name = candidate
                    name_idx = j
                    break

            if not name:
                continue

            # Find price + size in the next 15 lines after name
            price = None
            mrp = None
            size = None
            for k in range(name_idx + 1, min(name_idx + 16, len(lines))):
                kline = lines[k]
                # Size: "text: 500 ml" or "generic [ref=...]: 500 ml" or "generic: 1 ltr"
                if size is None:
                    sm = re.search(
                        r"(?:text|generic[^\n:]*):?\s*([\d.]+\s*(?:ml|g|kg|ltr?|pcs?|pack|Piece|piece|items?))\b",
                        kline, re.IGNORECASE,
                    )
                    if sm:
                        size = sm.group(1).strip()
                # Price: "₹ 29" or "₹29"
                pm = re.search(r"₹\s*(\d+(?:\.\d+)?)", kline)
                if pm:
                    val = float(pm.group(1))
                    if 5 <= val <= 10000:
                        if price is None:
                            price = val
                        elif mrp is None:
                            mrp = val
                            break

            if not price:
                continue

            # Try to extract brand from product name (first word if capitalized)
            brand = None
            name_parts = name.split()
            if len(name_parts) >= 2:
                first_word = name_parts[0]
                if first_word[0].isupper() and first_word.isalpha():
                    brand = first_word

            products.append({
                "id": f"im-{len(products) + 1}",
                "name": name,
                "brand": brand,
                "category": category,
                "subcategory": None,
                "packSize": size,
                "price": price,
                "totalPrice": mrp if mrp else price,
                "inStock": True,
                "maxSelectableQuantity": 5,
                "images": [],
            })

        return products
