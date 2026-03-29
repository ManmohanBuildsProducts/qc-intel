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
from src.db.repository import CanonicalRepository
from src.embeddings.catalog_export import export_catalog_to_json
from src.embeddings.kaggle_client import KaggleEmbeddingClient
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

    def run_embedding(self, category: str) -> dict | None:
        """Run Kaggle embedding pipeline: export catalog → push → poll → download."""
        from pathlib import Path

        cache_dir = settings.embedding_cache_dir
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        export_path = str(Path(cache_dir) / "catalog_export.json")

        export_catalog_to_json(self.conn, export_path, category=category)
        client = KaggleEmbeddingClient()
        return client.run_embedding_pipeline(export_path, category)

    async def run_normalization(self, category: str, match_results: dict | None = None) -> NormalizationResult:
        """Normalize products across platforms for a category."""
        service = NormalizerService(self.conn)
        return service.normalize_category(category, match_results=match_results)

    async def run_analysis(self, brand: str, category: str) -> MarketReport:
        """Generate a market intelligence report."""
        service = AnalyticsService(self.conn)
        return await service.generate_report(brand, category)

    def get_unmapped_categories(self, threshold: int | None = None) -> dict[str, int]:
        """Return categories with unmapped product counts at or above threshold.

        Args:
            threshold: Minimum unmapped count to include. Defaults to settings.auto_normalize_threshold.

        Returns:
            Dict of category -> unmapped count for categories meeting the threshold.
        """
        threshold = threshold if threshold is not None else settings.auto_normalize_threshold
        canonical_repo = CanonicalRepository(self.conn)
        counts = canonical_repo.get_unmapped_count_by_category()
        return {cat: count for cat, count in counts.items() if count >= threshold}

    async def check_and_normalize_after_scrape(
        self, threshold: int | None = None
    ) -> list[NormalizationResult]:
        """Detect unmapped products and auto-trigger embedding + normalization.

        For each category with unmapped count >= threshold:
        1. Run Kaggle embedding pipeline (export → push → poll → download)
        2. Run normalization with the fresh match results

        Args:
            threshold: Override for settings.auto_normalize_threshold.

        Returns:
            List of NormalizationResult for each category processed.
        """
        categories = self.get_unmapped_categories(threshold)
        if not categories:
            logger.info("No categories need normalization (all below threshold)")
            return []

        results = []
        for category, unmapped_count in categories.items():
            logger.info(
                "Category %r has %d unmapped products (threshold=%d) — running embedding + normalize",
                category, unmapped_count, threshold if threshold is not None else settings.auto_normalize_threshold,
            )

            # Step 1: Run Kaggle embedding pipeline
            match_results = self.run_embedding(category)
            if match_results is None:
                logger.warning("Embedding pipeline failed for %s — normalizing without matches", category)

            # Step 2: Normalize with fresh (or no) match results
            result = await self.run_normalization(category, match_results=match_results)
            results.append(result)
            logger.info(
                "  %s: %d canonical, %d mappings, %d unmapped",
                category,
                result.canonical_products_created,
                result.mappings_created,
                result.unmapped_count,
            )

        return results

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
        """Demo mode: seed all categories from fixtures, normalize, analyze. No live scraping."""
        from src.config.settings import DEFAULT_CATEGORIES

        logger.info("Running demo with fixture data (all categories)...")

        category_fixture_map: dict[str, list[tuple[Platform, str]]] = {
            "Dairy & Bread": [
                (Platform.BLINKIT, "blinkit_dairy.json"),
                (Platform.ZEPTO, "zepto_dairy.json"),
                (Platform.INSTAMART, "instamart_dairy.json"),
            ],
            "Fruits & Vegetables": [
                (Platform.BLINKIT, "blinkit_fv.json"),
                (Platform.ZEPTO, "zepto_fv.json"),
                (Platform.INSTAMART, "instamart_fv.json"),
            ],
            "Snacks & Munchies": [
                (Platform.BLINKIT, "blinkit_snacks.json"),
                (Platform.ZEPTO, "zepto_snacks.json"),
                (Platform.INSTAMART, "instamart_snacks.json"),
            ],
        }

        scrape_svc = ScrapeService(self.conn)
        for category in DEFAULT_CATEGORIES:
            fixtures = category_fixture_map.get(category, [])
            for platform, filename in fixtures:
                fixture_path = FIXTURES_DIR / filename
                if not fixture_path.exists():
                    logger.warning("Fixture not found: %s — skipping", fixture_path)
                    continue
                items = json.loads(fixture_path.read_text())
                scrape_svc.process_scrape_results(
                    items, platform, "122001", category, TimeOfDay.MORNING
                )
                logger.info("Seeded %s/%s: %d products", platform.value, category, len(items))

            result = await self.run_normalization(category)
            logger.info(
                "Normalized %s: %d canonical, %d mappings",
                category, result.canonical_products_created, result.mappings_created,
            )

        report = await self.run_analysis("Amul", "Dairy & Bread")
        logger.info("Report generated: %s", report.report_path)
        return report

    async def run_all_categories(
        self,
        categories: list[str] | None = None,
    ) -> list[NormalizationResult]:
        """Normalize all specified categories (default: DEFAULT_CATEGORIES). No scraping."""
        from src.config.settings import DEFAULT_CATEGORIES

        targets = categories or DEFAULT_CATEGORIES
        results = []
        for category in targets:
            logger.info("Normalizing category: %s", category)
            result = await self.run_normalization(category)
            results.append(result)
            logger.info(
                "  %s: %d canonical, %d mappings, %d unmapped",
                category,
                result.canonical_products_created,
                result.mappings_created,
                result.unmapped_count,
            )
        return results
