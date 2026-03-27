"""Swiggy Instamart scraper — deterministic Playwright-based product extraction."""

import logging
import os
import re

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config.settings import get_pincode_location
from src.models.product import Platform, ScrapeRun, TimeOfDay

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

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Override to use Chromium — less detectable by Swiggy's WAF than Firefox."""
        args = ["@playwright/mcp@latest", "--browser", "chromium"]
        proxy_url = os.environ.get("QC_PROXY_URL")
        if proxy_url:
            args += ["--proxy-server", proxy_url]
        server = StdioServerParameters(command="npx", args=args)
        async with stdio_client(server) as (read, write):
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
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        # Step 1: Navigate to Swiggy homepage to establish session cookies
        logger.info("[instamart] Navigating to Swiggy homepage...")
        await self._navigate(session, "https://www.swiggy.com")
        await self._wait(session)

        # Step 2: Navigate to Instamart and set Gurugram location cookies
        logger.info("[instamart] Navigating to Instamart...")
        await self._navigate(session, "https://www.swiggy.com/instamart")
        await self._wait(session)

        # Swiggy reads location from userLocation + _dl cookies (not HttpOnly)
        loc_json = (
            f'{{"address":"","lat":{lat},"lng":{lng},'
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
                    # Preserve real id from API — only assign sequential fallback if missing
                    if not item.get("id") or str(item["id"]).startswith("im-"):
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

        Each product card has the structure:
          generic "Delivery in XX MINS" [ref=...]:
            generic [ref=...]: XX MINS          ← skip
          generic [ref=...]: <Product Name>      ← 1-2 lines after delivery marker
          generic [ref=...]: <description>       ← skip
          ...
          generic [ref=...]: ₹ <price>           ← within next 15 lines
          generic [ref=...]: ₹ <mrp>             ← optional (if discounted)
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
                # Size: "text: 500 ml" or "generic [ref=...]: 500 ml"
                if size is None:
                    sm = re.search(
                        r"(?:text|generic[^\n:]*):?\s*([\d.]+\s*(?:ml|g|kg|ltr?|pcs?|pack|Piece|piece))\b",
                        kline, re.IGNORECASE,
                    )
                    if sm:
                        size = sm.group(1).strip()
                # Price
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

            products.append({
                "id": f"im-{len(products) + 1}",
                "name": name,
                "brand": None,
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
