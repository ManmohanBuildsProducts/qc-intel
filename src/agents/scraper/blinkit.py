"""Blinkit scraper — uses /v1/layout/search API via browser session."""

import json
import logging

from mcp import ClientSession

from src.config.settings import get_pincode_location
from src.models.product import Platform

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Search terms per category for broad product coverage
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

# JS template: calls /v1/layout/search and walks the response to collect all
# cart_item objects (richest product data: brand, inventory, image_url, etc.)
_EXTRACT_JS_TMPL = """async () => {{
    const r = await fetch(
        '/v1/layout/search?q={term}&search_type=type_to_search',
        {{
            method: 'POST',
            credentials: 'include',
            headers: {{
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'lat': '{lat}',
                'lon': '{lon}'
            }},
            body: '{{}}'
        }}
    );
    if (!r.ok) return '[]';
    const data = await r.json();
    const seen = new Set();
    const products = [];
    function walk(obj) {{
        if (!obj || typeof obj !== 'object') return;
        if (Array.isArray(obj)) {{ obj.forEach(walk); return; }}
        if (obj.cart_item && obj.cart_item.product_id) {{
            const item = obj.cart_item;
            if (!seen.has(item.product_id)) {{
                seen.add(item.product_id);
                products.push({{
                    id: item.product_id,
                    name: item.product_name || item.display_name || '',
                    brand: item.brand || null,
                    unit: item.unit || null,
                    price: item.price || 0,
                    mrp: item.mrp || null,
                    inventory: (typeof item.inventory === 'number') ? item.inventory : null,
                    image_url: item.image_url || null,
                    available: item.unavailable_quantity === 0,
                    max_allowed_quantity: item.quantity || 0
                }});
            }}
        }}
        for (const v of Object.values(obj)) {{
            if (v && typeof v === 'object') walk(v);
        }}
    }}
    walk(data);
    return JSON.stringify(products);
}}"""


class BlinkitScraper(BaseScraper):
    """Scraper for Blinkit — calls /v1/layout/search from within the browser session."""

    def __init__(self, conn):
        super().__init__(Platform.BLINKIT, conn)

    def get_system_prompt(self) -> str:
        return (
            "Blinkit scraper uses POST /v1/layout/search with lat/lon headers. "
            "Returns cart_item objects: product_id, brand, inventory (real stock), "
            "image_url, price, mrp, unit, available."
        )

    def get_scrape_url(self, pincode: str, category: str) -> str:
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266
        return f"https://blinkit.com/s/?q=milk&lat={lat}&lon={lng}"

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
    ) -> list[dict]:
        """Establish browser session then call the search API for each term."""
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        # Navigate to establish session cookies (API auth is cookie-based)
        logger.info("[blinkit] Establishing session for pincode=%s (%.4f, %.4f)", pincode, lat, lng)
        await self._navigate(session, f"https://blinkit.com/s/?q=milk&lat={lat}&lon={lng}")
        await self._wait(session)

        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_ids: set = set()

        for term in terms:
            items = await self._fetch_term(session, term, lat, lng)
            new_count = 0
            for item in items:
                pid = item.get("id") or item.get("name", "")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_items.append(item)
                    new_count += 1
            logger.info(
                "[blinkit] term=%s found=%d new=%d total=%d",
                term, len(items), new_count, len(all_items),
            )

        return all_items

    async def _fetch_term(
        self, session: ClientSession, term: str, lat: float, lng: float,
    ) -> list[dict]:
        """Call /v1/layout/search for one term; return list of product dicts."""
        # URL-encode spaces in term for the query string
        url_term = term.replace(" ", "+")
        js = _EXTRACT_JS_TMPL.format(term=url_term, lat=lat, lon=lng)
        raw = await self._evaluate(session, js)
        items = self._parse_json_from_evaluate(raw)
        if not isinstance(items, list):
            logger.warning(
                "[blinkit] API non-list response for term=%s: %s", term, str(raw)[:200]
            )
            return []
        return [i for i in items if i.get("name")]
