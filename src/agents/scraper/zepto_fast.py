"""Zepto fast scraper — extracts product data from Next.js RSC flight data.

Zepto's search API (bff-gateway.zepto.com) is called server-side by Next.js,
so window.fetch patching cannot intercept it. Instead, we extract product data
from the RSC (React Server Components) flight payload that Next.js embeds in
the page as self.__next_f. This contains the full API response including
inventory fields (availableQuantity, allocatedQuantity, outOfStock, etc.)
that are invisible in the rendered DOM.
"""

import asyncio
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
        args = [
            "@playwright/mcp@latest", "--browser", "firefox",
            "--headless", "--isolated", "--caps", "code-execution",
        ]
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
            logger.info("[zepto-fast] Searching: %s", term)

            # Use page.waitForResponse to intercept the BFF gateway API response.
            # This captures at the Playwright network level — works even though
            # the API is called server-side by Next.js (it still goes through the browser).
            bff_code = (
                "async (page) => {"
                "  var responsePromise = page.waitForResponse("
                "    function(r) { return r.url().includes('bff-gateway') && r.url().includes('search'); },"
                "    { timeout: 15000 }"
                "  );"
                f"  await page.goto('https://www.zepto.com/search?query={term}', "
                "    { waitUntil: 'domcontentloaded' });"
                "  var response = await responsePromise;"
                "  var body = await response.json();"
                "  var products = [];"
                "  function walk(obj) {"
                "    if (!obj || typeof obj !== 'object') return;"
                "    if (Array.isArray(obj)) { obj.forEach(walk); return; }"
                "    if (obj.availableQuantity !== undefined && obj.product && obj.mrp !== undefined) {"
                "      products.push(obj);"
                "    }"
                "    Object.values(obj).forEach(function(v) {"
                "      if (v && typeof v === 'object') walk(v);"
                "    });"
                "  }"
                "  walk(body);"
                "  return JSON.stringify(products);"
                "}"
            )

            result = await session.call_tool("browser_run_code", {"code": bff_code})
            bff_products = self._parse_json_result(result)

            if bff_products:
                items = self._normalize_rsc_products(bff_products, category)
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
                    "[zepto-fast] term=%s bff_products=%d total=%d",
                    term, len(items), len(all_items),
                )
            else:
                # Fallback: snapshot extraction (no inventory data)
                logger.warning("[zepto-fast] BFF capture failed for '%s', falling back to snapshot", term)
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

        # ATC probing: for products at inventory cap (50), find real stock
        # by clicking ADD + Increase on their product page (no login needed)
        _INV_CAP = 50
        capped = [item for item in all_items if (item.get("quantity") or 0) >= _INV_CAP]
        if capped:
            logger.info(
                "[zepto-fast] %d/%d products at inventory cap (%d), probing real stock via ATC...",
                len(capped), len(all_items), _INV_CAP,
            )
            probed = 0
            for item in capped:
                real_qty = await self._probe_atc_max(session, item)
                logger.info("[zepto-fast] ATC probe result: %s → %s", item.get("name", "?")[:30], real_qty)
                if real_qty and real_qty > _INV_CAP:
                    logger.info(
                        "[zepto-fast] ATC probe: %s | capped=%d real=%d",
                        item.get("name", "?")[:40], _INV_CAP, real_qty,
                    )
                    item["quantity"] = real_qty
                    probed += 1
            logger.info("[zepto-fast] ATC probing done: %d/%d uncapped", probed, len(capped))

        return all_items

    async def _probe_atc_max(self, session: ClientSession, item: dict) -> int | None:
        """Probe real stock for a capped product via ATC (no login needed).

        Uses MCP browser_click (accessibility tree) which is reliable,
        unlike Playwright CSS selectors which miss Zepto's custom components.
        """
        name = item.get("name", "")
        query = name.split("|")[0].split("(")[0].strip()[:40]
        url = f"https://www.zepto.com/search?query={query}"

        try:
            await session.call_tool("browser_navigate", {"url": url})
            await session.call_tool("browser_wait_for", {"time": 3000})

            # Find ADD button via accessibility snapshot
            snap = await session.call_tool("browser_snapshot", {})
            text = self._result_text(snap)
            add_refs = re.findall(r'button "ADD" \[ref=(\w+)\]', text)
            if not add_refs:
                return None

            # Click ADD
            await session.call_tool("browser_click", {"element": "ADD", "ref": add_refs[0]})
            await session.call_tool("browser_wait_for", {"time": 1500})

            # Find Increase button ref
            snap2 = await session.call_tool("browser_snapshot", {})
            text2 = self._result_text(snap2)
            inc_refs = re.findall(r'button "Increase quantity" \[ref=(\w+)\]', text2)
            if not inc_refs:
                return None

            # Click Increase repeatedly until quantity stops growing
            inc_ref = inc_refs[0]
            qty = 1
            stuck = 0
            for i in range(500):
                try:
                    await session.call_tool("browser_click", {
                        "element": "Increase quantity", "ref": inc_ref,
                    })
                except Exception:
                    break
                await asyncio.sleep(0.15)

                # Check qty every 10 clicks
                if (i + 1) % 10 == 0:
                    snap_c = await session.call_tool("browser_snapshot", {})
                    text_c = self._result_text(snap_c)
                    qty_match = re.search(r'generic \[ref=\w+\]: "(\d+)"', text_c)
                    new_qty = int(qty_match.group(1)) if qty_match else qty
                    # Update Increase ref in case it changed
                    new_inc = re.findall(r'button "Increase quantity" \[ref=(\w+)\]', text_c)
                    if new_inc:
                        inc_ref = new_inc[0]
                    if new_qty == qty:
                        stuck += 1
                        if stuck >= 2:
                            break
                    else:
                        stuck = 0
                        qty = new_qty

            # Remove from cart: click Decrease to remove
            dec_refs = re.findall(r'button "Decrease quantity" \[ref=(\w+)\]', text_c)
            if dec_refs:
                await session.call_tool("browser_click", {
                    "element": "Decrease quantity", "ref": dec_refs[0],
                })

            return qty
        except Exception as e:
            logger.warning("[zepto-fast] ATC probe failed for %s: %s", name[:30], e)
        return None

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
