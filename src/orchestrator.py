"""Pipeline orchestrator — coordinates scrape, estimate, normalize, and analyze stages."""

import json
import logging
from pathlib import Path

from src.agents.analyst import AnalyticsService
from src.agents.normalizer import NormalizerService
from src.agents.scraper import create_scraper
from src.agents.scraper.sales_service import SalesService
from src.agents.scraper.service import ScrapeService
from src.config.settings import settings
from src.db.init_db import init_db
from src.models.product import (
    MarketReport,
    NormalizationResult,
    Platform,
    ScrapeRun,
    TimeOfDay,
)

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


class PipelineOrchestrator:
    """Coordinates the full QC Intel pipeline."""

    def __init__(self, db_path: str | None = None) -> None:
        self.conn = init_db(db_path or settings.db_path)

    async def run_scrape(
        self, platform: Platform, pincode: str, category: str, time_of_day: TimeOfDay
    ) -> ScrapeRun:
        """Run a live scrape for a platform/pincode/category."""
        scraper = create_scraper(platform, self.conn)
        return await scraper.scrape(pincode, category, time_of_day)

    def run_sales_calculation(self, date: str, pincode: str | None = None) -> dict:
        """Calculate daily sales from morning/night observation pairs."""
        service = SalesService(self.conn)
        return service.calculate_daily_sales(date, pincode)

    async def run_normalization(self, category: str) -> NormalizationResult:
        """Normalize products across platforms for a category."""
        service = NormalizerService(self.conn)
        return service.normalize_category(category)

    async def run_analysis(self, brand: str, category: str) -> MarketReport:
        """Generate a market intelligence report."""
        service = AnalyticsService(self.conn)
        return await service.generate_report(brand, category)

    async def run_full_pipeline(
        self, brand: str, category: str, pincode: str, time_of_day: TimeOfDay
    ) -> MarketReport:
        """Run the entire pipeline: scrape → estimate → normalize → analyze."""
        # Scrape all platforms
        for platform in Platform:
            logger.info("Scraping %s for %s at %s", platform.value, category, pincode)
            await self.run_scrape(platform, pincode, category, time_of_day)

        # Calculate sales (needs morning + night, so only works if both exist)
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        self.run_sales_calculation(today, pincode)

        # Normalize
        await self.run_normalization(category)

        # Analyze
        return await self.run_analysis(brand, category)

    async def run_demo(self) -> MarketReport:
        """Demo mode: seed fixture data, run normalize + analyze. No live scraping."""
        logger.info("Running demo with fixture data...")

        # Seed all 3 platforms from fixtures
        scrape_svc = ScrapeService(self.conn)
        for platform, filename in [
            (Platform.BLINKIT, "blinkit_dairy.json"),
            (Platform.ZEPTO, "zepto_dairy.json"),
            (Platform.INSTAMART, "instamart_dairy.json"),
        ]:
            fixture_path = FIXTURES_DIR / filename
            items = json.loads(fixture_path.read_text())
            scrape_svc.process_scrape_results(
                items, platform, "122001", "Dairy & Bread", TimeOfDay.MORNING
            )
            logger.info("Seeded %s: %d products", platform.value, len(items))

        # Normalize
        result = await self.run_normalization("Dairy & Bread")
        logger.info(
            "Normalization: %d canonical, %d mappings",
            result.canonical_products_created,
            result.mappings_created,
        )

        # Generate report
        report = await self.run_analysis("Amul", "Dairy & Bread")
        logger.info("Report generated: %s", report.report_path)

        return report
