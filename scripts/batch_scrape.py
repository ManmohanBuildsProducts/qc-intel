"""Batch scrape runner — iterates categories × pincodes × platforms.

Usage:
    # Scrape all new FMCG categories, single pincode, morning
    python scripts/batch_scrape.py --morning --pincode 122001

    # Scrape specific categories across all seed pincodes
    python scripts/batch_scrape.py --morning --categories "Beverages" "Tea & Coffee"

    # Full run: all 9 categories × 8 pincodes × 3 platforms (takes ~4h)
    python scripts/batch_scrape.py --morning --all-pincodes

    # Night run
    python scripts/batch_scrape.py --night --pincode 122001
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import DEFAULT_CATEGORIES, SEED_PINCODES, settings
from src.models.product import Platform, TimeOfDay
from src.orchestrator import PipelineOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_batch(
    categories: list[str],
    pincodes: list[str],
    platforms: list[Platform],
    time_of_day: TimeOfDay,
) -> dict:
    """Run scrape for all combinations, returning a summary."""
    orch = PipelineOrchestrator()
    total = len(categories) * len(pincodes) * len(platforms)
    done = 0
    errors = 0
    total_products = 0

    for category in categories:
        for pincode in pincodes:
            for platform in platforms:
                done += 1
                label = f"[{done}/{total}] {platform.value}/{category}/{pincode}"
                logger.info("Starting %s", label)
                try:
                    run = await orch.run_scrape(platform, pincode, category, time_of_day)
                    total_products += run.products_found
                    logger.info(
                        "Done %s — %d products, %d errors",
                        label, run.products_found, run.errors,
                    )
                except Exception as e:
                    errors += 1
                    logger.error("FAILED %s — %s", label, e)

    return {
        "total_runs": total,
        "errors": errors,
        "total_products": total_products,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Batch scrape runner for QC Intel")

    # Time of day (required)
    tod = parser.add_mutually_exclusive_group(required=True)
    tod.add_argument("--morning", action="store_true")
    tod.add_argument("--night", action="store_true")

    # Pincode selection
    pin = parser.add_mutually_exclusive_group()
    pin.add_argument("--pincode", type=str, help="Single pincode (default: 122001)")
    pin.add_argument("--all-pincodes", action="store_true", help=f"All {len(SEED_PINCODES)} seed pincodes")

    # Category selection
    parser.add_argument(
        "--categories", nargs="+",
        help="Specific categories (default: all new non-Dairy categories)",
    )
    parser.add_argument(
        "--all-categories", action="store_true",
        help="Run all 9 DEFAULT_CATEGORIES",
    )

    # Platform selection
    parser.add_argument(
        "--platform", type=str,
        choices=["blinkit", "zepto", "instamart"],
        help="Single platform (default: all 3)",
    )

    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    time_of_day = TimeOfDay.MORNING if args.morning else TimeOfDay.NIGHT

    # Pincodes
    if args.all_pincodes:
        pincodes = SEED_PINCODES
    elif args.pincode:
        pincodes = [args.pincode]
    else:
        pincodes = ["122001"]  # default single pincode

    # Categories
    if args.categories:
        categories = args.categories
    elif args.all_categories:
        categories = DEFAULT_CATEGORIES
    else:
        # Default: the 6 new categories (skip Dairy/F&V/Snacks which already have data)
        categories = [c for c in DEFAULT_CATEGORIES if c not in {"Dairy & Bread", "Fruits & Vegetables", "Snacks & Munchies"}]

    # Platforms
    if args.platform:
        platforms = [Platform(args.platform)]
    else:
        platforms = list(Platform)

    logger.info(
        "Batch scrape: %d categories × %d pincodes × %d platforms = %d runs",
        len(categories), len(pincodes), len(platforms),
        len(categories) * len(pincodes) * len(platforms),
    )
    logger.info("Categories: %s", categories)
    logger.info("Pincodes: %s", pincodes)
    logger.info("Platforms: %s", [p.value for p in platforms])
    logger.info("Time of day: %s", time_of_day.value)

    summary = await run_batch(categories, pincodes, platforms, time_of_day)

    logger.info(
        "\n=== BATCH COMPLETE ===\n"
        "  Runs: %d\n  Errors: %d\n  Total products: %d",
        summary["total_runs"], summary["errors"], summary["total_products"],
    )


if __name__ == "__main__":
    asyncio.run(main())
