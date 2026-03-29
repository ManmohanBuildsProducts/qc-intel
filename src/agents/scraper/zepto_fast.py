"""Zepto fast scraper — extracts product data from Next.js RSC flight data.

Zepto's search API (bff-gateway.zepto.com) is called server-side by Next.js,
so window.fetch patching cannot intercept it. Instead, we extract product data
from the RSC (React Server Components) flight payload that Next.js embeds in
the page as self.__next_f. This contains the full API response including
inventory fields (availableQuantity, allocatedQuantity, outOfStock, etc.)
that are invisible in the rendered DOM.
"""

import json
import logging
import os
import re
import sqlite3

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config.settings import get_pincode_location
from src.models.product import Platform, ScrapeRun, TimeOfDay

from .service import ScrapeService
from .zepto import CATEGORY_SEARCH_TERMS

logger = logging.getLogger(__name__)


def _stealth_script_path() -> str:
    return os.path.join(os.path.dirname(__file__), "stealth.js")


# JS to extract all products from RSC flight data.
# Searches self.__next_f for objects containing "availableQuantity" (inventory)
# and "mrp" (price), then parses enclosing JSON objects.
_RSC_EXTRACT_JS = r"""() => {
    if (!self.__next_f) return JSON.stringify([]);

    let allText = '';
    for (const chunk of self.__next_f) {
        if (Array.isArray(chunk) && chunk.length >= 2 && typeof chunk[1] === 'string') {
            allText += chunk[1];
        }
    }

    const products = [];
    const seen = new Set();
    const regex = /"availableQuantity"\s*:/g;
    let m;
    while ((m = regex.exec(allText)) !== null) {
        let pos = m.index;
        let depth = 0;
        let start = -1;
        for (let i = pos; i >= Math.max(0, pos - 8000); i--) {
            if (allText[i] === '}') depth++;
            if (allText[i] === '{') {
                if (depth === 0) { start = i; break; }
                depth--;
            }
        }
        if (start < 0) continue;

        depth = 0;
        let end = start;
        for (let i = start; i < allText.length && i < start + 30000; i++) {
            if (allText[i] === '{') depth++;
            if (allText[i] === '}') {
                depth--;
                if (depth === 0) { end = i + 1; break; }
            }
        }
        if (end <= start) continue;

        try {
            const obj = JSON.parse(allText.substring(start, end));
            if (obj.availableQuantity !== undefined && obj.mrp !== undefined && obj.product) {
                const pid = obj.id || obj.objectId || '';
                if (pid && !seen.has(pid)) {
                    seen.add(pid);
                    products.push(obj);
                }
            }
        } catch(e) {}
    }

    return JSON.stringify(products);
}"""


class ZeptoFastScraper:
    """Fast Zepto scraper — extracts data from Next.js RSC flight payload."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.platform = Platform.ZEPTO
        self.conn = conn
        self.service = ScrapeService(conn)

    def _build_server(self) -> StdioServerParameters:
        args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
        stealth = _stealth_script_path()
        if os.path.exists(stealth):
            args += ["--init-script", stealth]
        return StdioServerParameters(command="npx", args=args)

    async def scrape(self, pincode: str, category: str, time_of_day: TimeOfDay) -> ScrapeRun:
        """Scrape Zepto by extracting RSC flight data."""
        location = get_pincode_location(pincode)
        lat = location.lat if location else 28.4595
        lng = location.lng if location else 77.0266

        items = await self._scrape_rsc(pincode, category, lat, lng)

        if not items:
            from src.models.exceptions import ScrapeError
            raise ScrapeError("zepto", "No products found via RSC extraction")

        logger.info("[zepto-fast] Scraped %d products for %s/%s", len(items), pincode, category)
        return self.service.process_scrape_results(items, self.platform, pincode, category, time_of_day)

    async def _scrape_rsc(
        self, pincode: str, category: str, lat: float, lng: float,
    ) -> list[dict]:
        async with stdio_client(self._build_server()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                try:
                    return await self._run_scrape(session, pincode, category, lat, lng)
                finally:
                    try:
                        await session.call_tool("browser_close", {})
                    except Exception:
                        pass

    async def _run_scrape(
        self, session: ClientSession, pincode: str, category: str,
        lat: float, lng: float,
    ) -> list[dict]:
        logger.info("[zepto-fast] Setting location for %s (%.4f, %.4f)", pincode, lat, lng)
        await session.call_tool("browser_navigate", {"url": "https://www.zepto.com"})
        await session.call_tool("browser_wait_for", {"time": 3000})

        await session.call_tool("browser_evaluate", {"function": (
            f'() => {{ '
            f'const pos = {{state: {{userPosition: {{'
            f'lat: {lat}, lng: {lng}, pincode: "{pincode}", '
            f'city: "Jaipur", address: "Jaipur, Rajasthan"'
            f'}}, _hasHydrated: true}}, version: 0}}; '
            f'localStorage.setItem("user-position", JSON.stringify(pos)); '
            f'return "location set"; }}'
        )})

        terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
        all_items: list[dict] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()

        for term in terms:
            url = f"https://www.zepto.com/search?query={term}"
            logger.info("[zepto-fast] Searching: %s", term)
            await session.call_tool("browser_navigate", {"url": url})
            await session.call_tool("browser_wait_for", {"time": 3000})

            # Scroll to trigger lazy-loaded RSC chunks, then wait for data
            await session.call_tool("browser_evaluate", {
                "function": "() => { window.scrollTo(0, 2000); return 'scrolled'; }",
            })
            await session.call_tool("browser_wait_for", {"time": 2000})

            # Extract products from RSC flight data
            result = await session.call_tool("browser_evaluate", {
                "function": _RSC_EXTRACT_JS,
            })
            rsc_products = self._parse_json_result(result)

            if rsc_products:
                items = self._normalize_rsc_products(rsc_products, category)
                for item in items:
                    pid = item.get("product_id", "")
                    name = item.get("name", "")
                    if not name:
                        continue
                    if pid and pid in seen_ids:
                        continue
                    if name in seen_names:
                        continue
                    if pid:
                        seen_ids.add(pid)
                    seen_names.add(name)
                    all_items.append(item)
                logger.info(
                    "[zepto-fast] term=%s rsc_products=%d total=%d",
                    term, len(items), len(all_items),
                )
            else:
                # Fallback: snapshot extraction (no inventory data)
                logger.warning("[zepto-fast] No RSC data for '%s', falling back to snapshot", term)
                from .zepto import ZeptoScraper

                snap_result = await session.call_tool("browser_snapshot", {})
                snap_text = self._result_text(snap_result)
                items = ZeptoScraper._extract_from_snapshot(snap_text, category)
                for item in items:
                    pid = item.get("product_id", "")
                    name = item.get("name", "")
                    if not name:
                        continue
                    if pid and pid in seen_ids:
                        continue
                    if name in seen_names:
                        continue
                    if pid:
                        seen_ids.add(pid)
                    seen_names.add(name)
                    all_items.append(item)
                logger.info(
                    "[zepto-fast] term=%s snapshot_items=%d total=%d",
                    term, len(items), len(all_items),
                )

        return all_items

    @staticmethod
    def _normalize_rsc_products(rsc_products: list[dict], category: str) -> list[dict]:
        """Convert RSC camelCase product objects to our standard schema.

        RSC products have:
          id, mrp (paise), discountedSellingPrice (paise), availableQuantity,
          allocatedQuantity, outOfStock, product{name, brand, id},
          productVariant{formattedPacksize, maxAllowedQuantity, weightInGms, images[]}
        """
        items = []
        for rsc in rsc_products:
            product = rsc.get("product") or {}
            variant = rsc.get("productVariant") or {}
            name = product.get("name", "")
            if not name:
                continue

            pid = rsc.get("id") or rsc.get("objectId", "")

            # RSC images are objects {path, height, width}, not URL strings.
            # Extract the path and build a CDN URL.
            raw_images = variant.get("images") or rsc.get("images") or []
            image_urls = []
            for img in raw_images:
                if isinstance(img, dict):
                    path = img.get("path", "")
                    if path:
                        image_urls.append(f"https://cdn.zeptonow.com/{path}")
                elif isinstance(img, str):
                    image_urls.append(img)

            items.append({
                "product_id": str(pid),
                "name": name,
                "brand_name": product.get("brand"),
                "category": category,
                "subcategory": None,
                "unit_quantity": variant.get("formattedPacksize"),
                # Prices in paise — convert to rupees
                "discounted_price": (rsc.get("discountedSellingPrice") or 0) / 100,
                "mrp": (rsc.get("mrp") or 0) / 100,
                "in_stock": not rsc.get("outOfStock", False),
                "max_cart_quantity": variant.get("maxAllowedQuantity", 0),
                # Real inventory count from BFF gateway API
                "quantity": rsc.get("availableQuantity"),
                "images": image_urls,
            })
        return items

    def _parse_json_result(self, result) -> list[dict]:
        """Parse JSON array from browser_evaluate result."""
        text = self._result_text(result)
        match = re.search(r"### Result\s*\n(.*?)(?:\n###|\Z)", text, re.DOTALL)
        if match:
            raw = match.group(1).strip()
            if raw.startswith('"') and raw.endswith('"'):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    pass
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return []
            return raw if isinstance(raw, list) else []
        return []

    @staticmethod
    def _result_text(result) -> str:
        text = ""
        for content in result.content:
            if hasattr(content, "text"):
                text += content.text
        return text
