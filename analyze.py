"""CLI entry point for QC Intel pipeline."""

import argparse
import asyncio
import logging
import sys

from src.models.product import Platform, TimeOfDay
from src.orchestrator import PipelineOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="QC Intel — Quick Commerce Intelligence Pipeline",
    )

    # Mode flags (mutually exclusive)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scrape", action="store_true", help="Run scraper agents")
    mode.add_argument("--calculate-sales", action="store_true", help="Calculate daily sales")
    mode.add_argument("--embed", action="store_true", help="Run Kaggle embedding pipeline (export → push → poll → download)")
    mode.add_argument("--normalize", action="store_true", help="Normalize products cross-platform")
    mode.add_argument("--normalize-all", action="store_true", help="Normalize all default categories")
    mode.add_argument("--analyze", action="store_true", help="Generate market intelligence report")
    mode.add_argument("--demo", action="store_true", help="Demo with fixture data (no live scraping)")
    mode.add_argument("--full-pipeline", action="store_true", help="Run full pipeline end-to-end")

    # Time of day
    parser.add_argument("--morning", action="store_true", help="Morning scrape")
    parser.add_argument("--night", action="store_true", help="Night scrape")

    # Filters
    parser.add_argument("--date", type=str, help="Date for sales calculation (YYYY-MM-DD)")
    parser.add_argument("--brand", type=str, default="Amul", help="Brand name for analysis")
    parser.add_argument("--category", type=str, default="Dairy & Bread", help="Category name")
    parser.add_argument("--pincode", type=str, default="122001", help="Pincode for scraping")
    parser.add_argument("--platform", type=str, help="Platform (blinkit, zepto, instamart)")

    return parser


async def async_main(args: argparse.Namespace) -> None:
    """Async main dispatcher."""
    orch = PipelineOrchestrator()

    if args.scrape:
        time_of_day = TimeOfDay.MORNING if args.morning else TimeOfDay.NIGHT
        platforms = [Platform(args.platform)] if args.platform else list(Platform)
        for platform in platforms:
            logger.info("Scraping %s (%s)...", platform.value, time_of_day.value)
            run = await orch.run_scrape(platform, args.pincode, args.category, time_of_day)
            logger.info("Done: %d products, %d errors", run.products_found, run.errors)

    elif args.calculate_sales:
        if not args.date:
            from datetime import datetime

            args.date = datetime.now().strftime("%Y-%m-%d")
        result = orch.run_sales_calculation(args.date)
        logger.info("Sales calculated: %s", result)

    elif args.embed:
        logger.info("Running Kaggle embedding pipeline for %s...", args.category)
        result = orch.run_embedding(args.category)
        if result:
            logger.info("Embedding complete: %d matches", result.get("num_matches", 0))
        else:
            logger.error("Embedding pipeline failed")
            sys.exit(1)

    elif args.normalize:
        result = await orch.run_normalization(args.category)
        logger.info(
            "Normalized: %d canonical, %d mappings, %d unmapped",
            result.canonical_products_created,
            result.mappings_created,
            result.unmapped_count,
        )

    elif args.normalize_all:
        results = await orch.run_all_categories()
        total_canonical = sum(r.canonical_products_created for r in results)
        total_mappings = sum(r.mappings_created for r in results)
        logger.info("All categories normalized: %d canonical, %d mappings total", total_canonical, total_mappings)

    elif args.analyze:
        report = await orch.run_analysis(args.brand, args.category)
        logger.info(
            "Report saved: %s (%d products, %d platforms)",
            report.report_path, report.product_count, report.platform_count,
        )

    elif args.demo:
        report = await orch.run_demo()
        logger.info("Demo complete! Report: %s", report.report_path)

    elif args.full_pipeline:
        time_of_day = TimeOfDay.MORNING if args.morning else TimeOfDay.NIGHT
        report = await orch.run_full_pipeline(args.brand, args.category, args.pincode, time_of_day)
        logger.info("Pipeline complete! Report: %s", report.report_path)

    else:
        logger.error("No mode specified. Use --help for options.")
        sys.exit(1)


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
