#!/usr/bin/env python3
"""Run a single scrape for Zepto and Instamart to capture raw API responses.

The fast scrapers have been modified to dump the first raw capture body to:
  - data/zepto_raw_capture.json
  - data/instamart_raw_capture.json

After running, inspect those files to find inventory fields.

Usage:
    python scripts/single_scrape_dump.py zepto
    python scripts/single_scrape_dump.py instamart
    python scripts/single_scrape_dump.py both
"""

import asyncio
import logging
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)

PINCODE = "302020"  # Jaipur Mansarovar
CATEGORY = "Dairy & Bread"


async def scrape_zepto():
    from src.agents.scraper.zepto_fast import ZeptoFastScraper
    from src.models.product import TimeOfDay

    # Remove old dump if exists
    dump_path = "data/zepto_raw_capture.json"
    if os.path.exists(dump_path):
        os.remove(dump_path)

    conn = sqlite3.connect("data/qc_intel.db")
    scraper = ZeptoFastScraper(conn)
    try:
        run = await scraper.scrape(PINCODE, CATEGORY, TimeOfDay.MORNING)
        print(f"\nZepto scrape completed: {run.products_found} products")
    except Exception as e:
        print(f"\nZepto scrape failed: {e}")
    finally:
        conn.close()

    if os.path.exists(dump_path):
        size = os.path.getsize(dump_path)
        print(f"Raw capture saved: {dump_path} ({size:,} bytes)")
        print("Run: python3 -c \"import json; d=json.load(open('data/zepto_raw_capture.json')); ...\" to inspect")
    else:
        print("WARNING: No raw capture file created")


async def scrape_instamart():
    from src.agents.scraper.instamart_fast import InstamartFastScraper
    from src.models.product import TimeOfDay

    dump_path = "data/instamart_raw_capture.json"
    if os.path.exists(dump_path):
        os.remove(dump_path)

    conn = sqlite3.connect("data/qc_intel.db")
    scraper = InstamartFastScraper(conn)
    try:
        run = await scraper.scrape(PINCODE, CATEGORY, TimeOfDay.MORNING)
        print(f"\nInstamart scrape completed: {run.products_found} products")
    except Exception as e:
        print(f"\nInstamart scrape failed: {e}")
    finally:
        conn.close()

    if os.path.exists(dump_path):
        size = os.path.getsize(dump_path)
        print(f"Raw capture saved: {dump_path} ({size:,} bytes)")
    else:
        print("WARNING: No raw capture file created")


async def main():
    platform = sys.argv[1] if len(sys.argv) > 1 else "both"

    if platform in ("zepto", "both"):
        print("=" * 60)
        print("  ZEPTO — Single scrape to capture raw API response")
        print("=" * 60)
        await scrape_zepto()

    if platform in ("instamart", "both"):
        print("\n" + "=" * 60)
        print("  INSTAMART — Single scrape to capture raw API response")
        print("=" * 60)
        await scrape_instamart()

    print("\n" + "=" * 60)
    print("  Next: inspect the raw captures for inventory fields")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
