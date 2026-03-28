"""Fast single-session Instamart night scraper — 1 browser per pincode, all categories.

Resumes from DB: skips (pincode, category) combos already scraped tonight.

Usage:
    .venv/bin/python3 scripts/fast_instamart_night.py
"""

import asyncio
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.agents.scraper.instamart import CATEGORY_SEARCH_TERMS, InstamartScraper
from src.agents.scraper.service import ScrapeService
from src.config.settings import DEFAULT_CATEGORIES, JAIPUR_PINCODES, get_pincode_location
from src.db.init_db import init_db
from src.models.product import Platform, TimeOfDay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("fast-instamart")

TIME_OF_DAY = TimeOfDay.NIGHT


def _stealth_path() -> str:
    return str(Path(__file__).parent.parent / "src" / "agents" / "scraper" / "stealth.js")


def _result_text(result) -> str:
    text = ""
    for content in result.content:
        if hasattr(content, "text"):
            text += content.text
    return text


async def scrape_instamart_all_categories(
    pincode: str, categories: list[str], conn: sqlite3.Connection,
) -> dict:
    """Open ONE Chromium browser for Instamart, scrape all categories via search+snapshot."""
    location = get_pincode_location(pincode)
    lat = location.lat if location else 28.4595
    lng = location.lng if location else 77.0266

    # Instamart uses Chromium (less detectable by Swiggy WAF)
    args = ["@playwright/mcp@latest", "--browser", "chromium", "--headless", "--isolated"]
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
                # Navigate ONCE to Swiggy homepage to establish session + WAF token
                logger.info("[instamart/%s] Establishing session...", pincode)
                await session.call_tool("browser_navigate", {"url": "https://www.swiggy.com"})
                await session.call_tool("browser_wait_for", {"time": 3000})

                # Set location cookies ONCE
                loc_json = (
                    f'{{"address":"Jaipur","lat":{lat},"lng":{lng},'
                    f'"id":"","annotation":"","name":"Jaipur"}}'
                )
                await session.call_tool("browser_evaluate", {"function": (
                    f'() => {{ '
                    f'const loc = encodeURIComponent(\'{loc_json}\'); '
                    f'document.cookie = "userLocation=" + loc + ";path=/;max-age=86400"; '
                    f'document.cookie = "_dl={lat};path=/;max-age=86400"; '
                    f'return "location set"; }}'
                )})
                logger.info("[instamart/%s] Location set (%.4f, %.4f)", pincode, lat, lng)

                for category in categories:
                    terms = CATEGORY_SEARCH_TERMS.get(category, [category.lower()])
                    all_items: list[dict] = []
                    seen_names: set[str] = set()

                    for term in terms:
                        url = f"https://www.swiggy.com/instamart/search?custom_back=true&query={term}"
                        await session.call_tool("browser_navigate", {"url": url})
                        await session.call_tool("browser_wait_for", {"time": 2000})

                        # Progressive scroll to trigger lazy loading
                        for scroll_y in (500, 1500, 3000):
                            await session.call_tool("browser_evaluate", {
                                "function": f'() => {{ window.scrollTo(0, {scroll_y}); return "ok"; }}',
                            })
                            await session.call_tool("browser_wait_for", {"time": 1500})

                        # Extract from snapshot
                        snapshot = _result_text(
                            await session.call_tool("browser_snapshot", {})
                        )
                        items = InstamartScraper._extract_from_snapshot(snapshot, category)

                        # Retry once if empty
                        if not items:
                            logger.info("[instamart/%s] Retrying '%s'...", pincode, term)
                            await session.call_tool("browser_wait_for", {"time": 3000})
                            await session.call_tool("browser_evaluate", {
                                "function": '() => { window.scrollTo(0, document.body.scrollHeight); return "ok"; }',
                            })
                            await session.call_tool("browser_wait_for", {"time": 2000})
                            snapshot = _result_text(
                                await session.call_tool("browser_snapshot", {})
                            )
                            items = InstamartScraper._extract_from_snapshot(snapshot, category)

                        for item in items:
                            name = item.get("name", "")
                            if name and name not in seen_names:
                                seen_names.add(name)
                                if not item.get("id") or str(item["id"]).startswith("im-"):
                                    item["id"] = f"im-{len(all_items) + 1}"
                                all_items.append(item)

                    if all_items:
                        run = service.process_scrape_results(
                            all_items, Platform.INSTAMART, pincode, category, TIME_OF_DAY,
                        )
                        stats["products"] += run.products_found
                        stats["categories"] += 1
                        logger.info(
                            "[instamart/%s] %s: %d products",
                            pincode, category, run.products_found,
                        )
                    else:
                        stats["errors"] += 1
                        logger.warning("[instamart/%s] %s: no products", pincode, category)

            finally:
                try:
                    await session.call_tool("browser_close", {})
                except Exception:
                    pass

    return stats


async def main():
    pincodes = [p.pincode for p in JAIPUR_PINCODES]
    categories = DEFAULT_CATEGORIES
    conn = init_db()

    # Check what's already done tonight
    cursor = conn.cursor()
    existing = set()
    for row in cursor.execute(
        "SELECT pincode, category FROM scrape_runs "
        "WHERE platform = 'instamart' AND time_of_day = 'night' AND started_at >= '2026-03-28'"
    ):
        existing.add((row[0], row[1]))
    logger.info("Already completed: %d Instamart night runs (will skip)", len(existing))

    # Build per-pincode category lists
    work: dict[str, list[str]] = {}
    for pincode in pincodes:
        cats = [c for c in categories if (pincode, c) not in existing]
        if cats:
            work[pincode] = cats

    total = sum(len(v) for v in work.values())
    logger.info("Remaining: %d Instamart category-runs across %d pincodes", total, len(work))

    if not work:
        logger.info("Nothing to do — all Instamart night runs complete!")
        return

    # Run 2 pincodes concurrently (2 Chromium browsers)
    semaphore = asyncio.Semaphore(2)
    total_stats = {"products": 0, "errors": 0}

    async def run_pincode(pincode: str):
        async with semaphore:
            try:
                r = await scrape_instamart_all_categories(pincode, work[pincode], conn)
                total_stats["products"] += r["products"]
                total_stats["errors"] += r["errors"]
            except Exception as e:
                logger.error("[instamart/%s] Failed: %s", pincode, e)
                total_stats["errors"] += 1

    await asyncio.gather(*[run_pincode(p) for p in work])

    logger.info(
        "\n=== INSTAMART NIGHT SCRAPE COMPLETE ===\n"
        "  Total products: %d\n  Errors: %d",
        total_stats["products"], total_stats["errors"],
    )


if __name__ == "__main__":
    asyncio.run(main())
