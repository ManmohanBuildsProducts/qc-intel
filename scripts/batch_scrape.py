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

from src.config.settings import DEFAULT_CATEGORIES, JAIPUR_SEED_PINCODES, SEED_PINCODES
from src.models.product import Platform, TimeOfDay
from src.orchestrator import PipelineOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _scrape_single(
    orch: PipelineOrchestrator,
    platform: Platform,
    pincode: str,
    category: str,
    time_of_day: TimeOfDay,
    semaphore: asyncio.Semaphore,
) -> tuple[int, int]:
    """Scrape one (platform, category, pincode) combo. Returns (products, errors).

    Each call gets its own browser instance (--isolated), so any combination
    of platforms can run concurrently without profile lock conflicts.
    """
    async with semaphore:
        label = f"{platform.value}/{category}/{pincode}"
        logger.info("Starting %s", label)
        try:
            run = await orch.run_scrape(platform, pincode, category, time_of_day)
            logger.info("Done %s — %d products", label, run.products_found)
            return run.products_found, 0
        except Exception as e:
            logger.error("FAILED %s — %s", label, e)
            return 0, 1


async def run_batch(
    categories: list[str],
    pincodes: list[str],
    platforms: list[Platform],
    time_of_day: TimeOfDay,
    parallel_platforms: bool = False,
    concurrency: int = 1,
) -> dict:
    """Run scrape for all combinations, returning a summary.

    All (platform, category, pincode) combos are flattened into individual tasks
    and throttled by the semaphore. With --isolated browsers, any platform combo
    can run concurrently. concurrency controls total parallel browser instances.
    """
    orch = PipelineOrchestrator()
    total = len(categories) * len(pincodes) * len(platforms)
    semaphore = asyncio.Semaphore(concurrency)

    logger.info(
        "Concurrency: %d parallel browsers, %d total jobs",
        concurrency, total,
    )

    tasks = []
    for category in categories:
        for pincode in pincodes:
            for platform in platforms:
                tasks.append(
                    _scrape_single(
                        orch, platform, pincode, category, time_of_day, semaphore,
                    )
                )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    total_products = 0
    total_errors = 0
    for result in results:
        if isinstance(result, Exception):
            total_errors += 1
            logger.error("Job failed: %s", result)
        else:
            products, errors = result
            total_products += products
            total_errors += errors

    return {
        "total_runs": total,
        "errors": total_errors,
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
    pin.add_argument("--all-pincodes", action="store_true", help=f"All {len(SEED_PINCODES)} Gurugram seed pincodes")
    pin.add_argument(
        "--jaipur", action="store_true",
        help=f"All {len(JAIPUR_SEED_PINCODES)} Jaipur triple-overlap pincodes",
    )

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

    # Parallelism
    parser.add_argument(
        "--parallel", action="store_true",
        help="Scrape all platforms concurrently per (category, pincode) — 3x faster",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Number of pincodes to scrape concurrently (default: 1, recommended: 4)",
    )

    # Speed
    parser.add_argument(
        "--fast", action="store_true",
        help="Use XHR-intercepting fast scrapers for Zepto/Instamart (~10x faster)",
    )

    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    time_of_day = TimeOfDay.MORNING if args.morning else TimeOfDay.NIGHT

    # Fast mode: use XHR-intercepting scrapers
    if args.fast:
        import os
        os.environ["QC_FAST_SCRAPE"] = "1"

    # Pincodes
    if args.all_pincodes:
        pincodes = SEED_PINCODES
    elif args.jaipur:
        pincodes = JAIPUR_SEED_PINCODES
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
        existing = {"Dairy & Bread", "Fruits & Vegetables", "Snacks & Munchies"}
        categories = [c for c in DEFAULT_CATEGORIES if c not in existing]

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

    summary = await run_batch(
        categories, pincodes, platforms, time_of_day,
        parallel_platforms=args.parallel,
        concurrency=args.concurrency,
    )

    logger.info(
        "\n=== BATCH COMPLETE ===\n"
        "  Runs: %d\n  Errors: %d\n  Total products: %d",
        summary["total_runs"], summary["errors"], summary["total_products"],
    )


if __name__ == "__main__":
    asyncio.run(main())
