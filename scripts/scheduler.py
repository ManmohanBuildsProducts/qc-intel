"""Nightly sales cron daemon — automates morning + night scrape + sales calculation.

Usage:
    python scripts/scheduler.py            # Start daemon (blocks)
    python scripts/scheduler.py --dry-run  # Fire both jobs immediately, then exit

Env vars:
    QC_SCRAPE_PINCODES   Comma-separated pincodes (default: all SEED_PINCODES)
    QC_LOG_DIR           Log directory (default: logs/)
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# --- Logging setup (must happen before other project imports that call basicConfig) ---

LOG_DIR = Path(os.environ.get("QC_LOG_DIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

_fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
_file_handler = RotatingFileHandler(
    LOG_DIR / "scheduler.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=7,
)
_file_handler.setFormatter(_fmt)
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_fmt)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(_file_handler)
root_logger.addHandler(_stream_handler)

from scripts.batch_scrape import run_batch  # noqa: E402 — after logging setup
from src.config.settings import DEFAULT_CATEGORIES, SEED_PINCODES  # noqa: E402
from src.models.product import Platform, TimeOfDay  # noqa: E402
from src.orchestrator import PipelineOrchestrator  # noqa: E402
logger = logging.getLogger(__name__)


def _get_pincodes() -> list[str]:
    """Return pincodes from env var or single default pincode (122001).

    Cron default is 1 pincode to keep each job under ~1h.
    Set QC_SCRAPE_PINCODES=122001,122002,... to expand coverage.
    Set QC_SCRAPE_PINCODES=all to use all 8 SEED_PINCODES (~25h, for manual runs).
    """
    raw = os.environ.get("QC_SCRAPE_PINCODES", "").strip()
    if raw == "all":
        return list(SEED_PINCODES)
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    return ["122001"]  # default: 1 pincode × 9 categories × parallel platforms ≈ 54 min


async def _scrape_and_calculate(time_of_day: TimeOfDay) -> None:
    """Run batch scrape then calculate sales for today (sequential, no race conditions)."""
    pincodes = _get_pincodes()
    today = datetime.now().strftime("%Y-%m-%d")

    logger.info(
        "=== %s JOB START === date=%s pincodes=%d categories=%d platforms=3",
        time_of_day.value.upper(),
        today,
        len(pincodes),
        len(DEFAULT_CATEGORIES),
    )

    # Step 1: batch scrape — platforms run in parallel per (category, pincode) for ~3x speedup
    summary = await run_batch(
        categories=DEFAULT_CATEGORIES,
        pincodes=pincodes,
        platforms=list(Platform),
        time_of_day=time_of_day,
        parallel_platforms=True,
    )
    logger.info(
        "Scrape complete — runs=%d errors=%d products=%d",
        summary["total_runs"],
        summary["errors"],
        summary["total_products"],
    )

    # Step 2: sales calculation (runs after scrape finishes — no race)
    logger.info("Calculating sales for %s ...", today)
    orch = PipelineOrchestrator()
    result = orch.run_sales_calculation(today)
    logger.info("Sales calculation complete — %s", result)

    logger.info("=== %s JOB DONE ===", time_of_day.value.upper())


def job_morning() -> None:
    asyncio.run(_scrape_and_calculate(TimeOfDay.MORNING))


def job_night() -> None:
    asyncio.run(_scrape_and_calculate(TimeOfDay.NIGHT))


def main() -> None:
    parser = argparse.ArgumentParser(description="QC Intel scheduler daemon")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fire both jobs immediately and exit (no waiting for cron times)",
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("=== DRY RUN — firing both jobs immediately ===")
        job_morning()
        job_night()
        logger.info("=== DRY RUN COMPLETE ===")
        return

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    scheduler.add_job(
        job_morning,
        trigger=CronTrigger(hour=10, minute=30),
        id="morning_scrape",
        name="Morning scrape + sales calc (10:30 IST)",
        max_instances=1,
        misfire_grace_time=3600,  # allow up to 1h late start
    )

    scheduler.add_job(
        job_night,
        trigger=CronTrigger(hour=23, minute=30),
        id="night_scrape",
        name="Night scrape + sales calc (23:30 IST)",
        max_instances=1,
        misfire_grace_time=3600,
    )

    logger.info("Scheduler starting — morning=10:30 IST, night=23:30 IST")
    logger.info("Pincodes: %s", _get_pincodes())
    logger.info("Log dir: %s", LOG_DIR.resolve())

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
