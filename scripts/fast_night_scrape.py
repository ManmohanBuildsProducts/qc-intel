"""Fast single-session night scraper — 1 browser per (platform, pincode).

Instead of spawning 189 browsers (1 per job), opens 1 browser per platform/pincode
and runs ALL categories through it. Cuts ~5h → ~35min.

Usage:
    .venv/bin/python3 scripts/fast_night_scrape.py
"""

import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.agents.scraper.blinkit import CATEGORY_SEARCH_TERMS as BLINKIT_TERMS, _EXTRACT_JS_TMPL
from src.agents.scraper.parsers import parse_blinkit_products, parse_zepto_products
from src.agents.scraper.service import ScrapeService
from src.agents.scraper.zepto import CATEGORY_SEARCH_TERMS as ZEPTO_TERMS, ZeptoScraper
from src.config.settings import DEFAULT_CATEGORIES, JAIPUR_PINCODES, get_pincode_location
from src.db.init_db import init_db
from src.models.product import Platform, TimeOfDay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("fast-night")

TIME_OF_DAY = TimeOfDay.NIGHT


def _stealth_path() -> str:
    return str(Path(__file__).parent.parent / "src" / "agents" / "scraper" / "stealth.js")


def _result_text(result) -> str:
    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text
    return text


def _parse_json_from_evaluate(text: str):
    """Parse JSON from browser_evaluate result."""
    import json
    import re

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
                pass
        else:
            return raw

    bracket_start = text.find("[")
    if bracket_start >= 0:
        depth = 0
        for i in range(bracket_start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[bracket_start : i + 1])
                    except json.JSONDecodeError:
                        pass
                    break
    return None


# ---------------------------------------------------------------------------
# Blinkit: 1 browser, fetch() API calls for all categories
# ---------------------------------------------------------------------------
async def scrape_blinkit_all_categories(
    pincode: str, categories: list[str], conn: sqlite3.Connection,
) -> dict:
    """Open ONE browser for Blinkit, scrape all categories via fetch() API."""
    location = get_pincode_location(pincode)
    lat = location.lat if location else 28.4595
    lng = location.lng if location else 77.0266

    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    stealth = _stealth_path()
    if os.path.exists(stealth):
        args += ["--init-script", stealth]
    server = StdioServerParameters(command="npx", args=args)

    service = ScrapeService(conn)
    stats = {"products": 0, "errors": 0, "categories": 0}

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                # Navigate ONCE to establish session cookies
                logger.info("[blinkit/%s] Establishing session...", pincode)
                await session.call_tool(
                    "browser_navigate",
                    {"url": f"https://blinkit.com/s/?q=milk&lat={lat}&lon={lng}"},
                )
                await session.call_tool("browser_wait_for", {"time": 3000})

                for category in categories:
                    terms = BLINKIT_TERMS.get(category, [category.lower()])
                    all_items: list[dict] = []
                    seen_ids: set = set()

                    for term in terms:
                        url_term = term.replace(" ", "+")
                        js = _EXTRACT_JS_TMPL.format(term=url_term, lat=lat, lon=lng)
                        raw = _result_text(
                            await session.call_tool("browser_evaluate", {"function": js})
                        )
                        items = _parse_json_from_evaluate(raw)
                        if isinstance(items, list):
                            for item in items:
                                pid = item.get("id") or item.get("name", "")
                                if pid and pid not in seen_ids:
                                    seen_ids.add(pid)
                                    all_items.append(item)

                    if all_items:
                        run = service.process_scrape_results(
                            all_items, Platform.BLINKIT, pincode, category, TIME_OF_DAY,
                        )
                        stats["products"] += run.products_found
                        stats["categories"] += 1
                        logger.info(
                            "[blinkit/%s] %s: %d products",
                            pincode, category, run.products_found,
                        )
                    else:
                        stats["errors"] += 1
                        logger.warning("[blinkit/%s] %s: no products", pincode, category)

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass

    return stats


# ---------------------------------------------------------------------------
# Zepto: 1 browser, navigate+snapshot for all categories
# ---------------------------------------------------------------------------
async def scrape_zepto_all_categories(
    pincode: str, categories: list[str], conn: sqlite3.Connection,
) -> dict:
    """Open ONE browser for Zepto, scrape all categories via search+snapshot."""
    location = get_pincode_location(pincode)
    lat = location.lat if location else 28.4595
    lng = location.lng if location else 77.0266

    args = ["@playwright/mcp@latest", "--browser", "firefox", "--headless", "--isolated"]
    stealth = _stealth_path()
    if os.path.exists(stealth):
        args += ["--init-script", stealth]
    server = StdioServerParameters(command="npx", args=args)

    service = ScrapeService(conn)
    stats = {"products": 0, "errors": 0, "categories": 0}

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                # Navigate ONCE to homepage + set location
                logger.info("[zepto/%s] Setting location (%.4f, %.4f)...", pincode, lat, lng)
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

                location_clicked = False

                for category in categories:
                    terms = ZEPTO_TERMS.get(category, [category.lower()])
                    all_items: list[dict] = []
                    seen_names: set[str] = set()

                    for term in terms:
                        url = f"https://www.zepto.com/search?query={term}"
                        await session.call_tool("browser_navigate", {"url": url})
                        await session.call_tool("browser_wait_for", {"time": 2000})

                        # First search: click Select Location if needed
                        if not location_clicked:
                            snap = _result_text(
                                await session.call_tool("browser_snapshot", {})
                            )
                            if "Select Location" in snap:
                                try:
                                    await session.call_tool(
                                        "browser_click",
                                        {"element": "Select Location button", "ref": ""},
                                    )
                                    location_clicked = True
                                    await session.call_tool("browser_wait_for", {"time": 2000})
                                except Exception:
                                    pass

                        # Scroll to load more
                        await session.call_tool("browser_evaluate", {
                            "function": '() => { window.scrollTo(0, 1000); return "ok"; }',
                        })
                        await session.call_tool("browser_wait_for", {"time": 1500})

                        # Extract from snapshot
                        snapshot = _result_text(
                            await session.call_tool("browser_snapshot", {})
                        )
                        items = ZeptoScraper._extract_from_snapshot(snapshot, category)
                        for item in items:
                            name = item.get("name", "")
                            if name and name not in seen_names:
                                seen_names.add(name)
                                if not item.get("product_id"):
                                    item["product_id"] = f"z-{len(all_items) + 1}"
                                all_items.append(item)

                    if all_items:
                        run = service.process_scrape_results(
                            all_items, Platform.ZEPTO, pincode, category, TIME_OF_DAY,
                        )
                        stats["products"] += run.products_found
                        stats["categories"] += 1
                        logger.info(
                            "[zepto/%s] %s: %d products",
                            pincode, category, run.products_found,
                        )
                    else:
                        stats["errors"] += 1
                        logger.warning("[zepto/%s] %s: no products", pincode, category)

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass

    return stats


# ---------------------------------------------------------------------------
# Main: run Blinkit + Zepto concurrently, 2 pincodes at a time
# ---------------------------------------------------------------------------
async def main():
    pincodes = [p.pincode for p in JAIPUR_PINCODES]
    categories = DEFAULT_CATEGORIES
    conn = init_db()

    logger.info(
        "Fast night scrape: %d pincodes × %d categories × 2 platforms (Blinkit + Zepto)",
        len(pincodes), len(categories),
    )
    logger.info("Pincodes: %s", pincodes)
    logger.info("Skipping Instamart (too slow for battery-constrained run)")

    # Check which (platform, pincode, category) combos already have night data today
    cursor = conn.cursor()
    existing = set()
    for row in cursor.execute(
        "SELECT platform, pincode, category FROM scrape_runs "
        "WHERE date(started_at) = date('now') AND time_of_day = 'night'"
    ):
        existing.add((row[0], row[1], row[2]))
    logger.info("Already completed: %d runs (will skip)", len(existing))

    # Build per-pincode category lists, excluding already-done combos
    blinkit_work: dict[str, list[str]] = {}
    zepto_work: dict[str, list[str]] = {}
    for pincode in pincodes:
        bl_cats = [c for c in categories if ("blinkit", pincode, c) not in existing]
        ze_cats = [c for c in categories if ("zepto", pincode, c) not in existing]
        if bl_cats:
            blinkit_work[pincode] = bl_cats
        if ze_cats:
            zepto_work[pincode] = ze_cats

    total_blinkit = sum(len(v) for v in blinkit_work.values())
    total_zepto = sum(len(v) for v in zepto_work.values())
    logger.info("Remaining: %d Blinkit + %d Zepto category-runs", total_blinkit, total_zepto)

    # Run 2 pincodes concurrently (4 browsers max: 2 Blinkit + 2 Zepto)
    semaphore = asyncio.Semaphore(2)
    total_stats = {"products": 0, "errors": 0}

    async def run_pincode(pincode: str):
        async with semaphore:
            tasks = []
            if pincode in blinkit_work:
                tasks.append(scrape_blinkit_all_categories(pincode, blinkit_work[pincode], conn))
            if pincode in zepto_work:
                tasks.append(scrape_zepto_all_categories(pincode, zepto_work[pincode], conn))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error("Pincode %s failed: %s", pincode, r)
                    total_stats["errors"] += 1
                else:
                    total_stats["products"] += r["products"]
                    total_stats["errors"] += r["errors"]

    await asyncio.gather(*[run_pincode(p) for p in pincodes])

    logger.info(
        "\n=== FAST NIGHT SCRAPE COMPLETE ===\n"
        "  Total products: %d\n  Errors: %d",
        total_stats["products"], total_stats["errors"],
    )


if __name__ == "__main__":
    asyncio.run(main())
