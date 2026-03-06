"""Tests for pipeline orchestrator and CLI entry point."""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.product import Platform, TimeOfDay


class TestPipelineOrchestrator:
    def test_init_creates_db(self, tmp_path: Path) -> None:
        from src.orchestrator import PipelineOrchestrator

        db_path = str(tmp_path / "test.db")
        orch = PipelineOrchestrator(db_path=db_path)
        assert orch.conn is not None
        # Verify tables exist
        tables = orch.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        assert len(tables) >= 6

    def test_sales_calculation_flow(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
    ) -> None:
        from datetime import datetime

        from src.agents.scraper.service import ScrapeService
        from src.db.repository import CatalogRepository, ObservationRepository
        from src.models.product import ProductObservation
        from src.orchestrator import PipelineOrchestrator

        # Seed morning observations via ScrapeService
        svc = ScrapeService(db_session)
        svc.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        # Seed night observations with different quantities (simulate sales)
        catalog_repo = CatalogRepository(db_session)
        obs_repo = ObservationRepository(db_session)
        products = catalog_repo.get_by_platform(Platform.BLINKIT)
        for p in products:
            obs_repo.insert_observation(ProductObservation(
                catalog_id=p.id,
                scrape_run_id="run-night",
                pincode="122001",
                price=29.0,
                max_cart_qty=max(0, 3),  # night qty < morning qty
                time_of_day=TimeOfDay.NIGHT,
            ))

        # Test via orchestrator
        orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
        orch.conn = db_session

        today = datetime.utcnow().strftime("%Y-%m-%d")
        result = orch.run_sales_calculation(today, "122001")
        assert result["records_created"] > 0

    @pytest.mark.asyncio
    async def test_run_normalization(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
        zepto_fixture_data: list[dict],
        instamart_fixture_data: list[dict],
    ) -> None:
        from src.agents.scraper.service import ScrapeService
        from src.orchestrator import PipelineOrchestrator

        # Seed all platforms
        svc = ScrapeService(db_session)
        svc.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )
        svc.process_scrape_results(
            zepto_fixture_data, Platform.ZEPTO, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )
        svc.process_scrape_results(
            instamart_fixture_data, Platform.INSTAMART, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
        orch.conn = db_session

        result = await orch.run_normalization("Dairy & Bread")
        assert result.canonical_products_created > 0
        assert result.mappings_created > 0

    @pytest.mark.asyncio
    async def test_run_analysis_mocked(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
    ) -> None:
        from src.agents.scraper.service import ScrapeService
        from src.orchestrator import PipelineOrchestrator

        svc = ScrapeService(db_session)
        svc.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
        orch.conn = db_session

        mock_report = "## Executive Summary\nTest.\n\n## Brand Overview\nTest."
        mock_response = MagicMock()
        mock_response.text = mock_report

        with patch("src.agents.analyst.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            report = await orch.run_analysis("Amul", "Dairy & Bread")

        assert report.brand == "Amul"
        assert report.product_count > 0

    @pytest.mark.asyncio
    async def test_demo_seeds_data_and_runs(self, tmp_path: Path) -> None:
        from src.orchestrator import PipelineOrchestrator

        db_path = str(tmp_path / "demo.db")
        orch = PipelineOrchestrator(db_path=db_path)

        mock_report = "\n\n".join([f"## Section {i}\nContent." for i in range(8)])
        mock_response = MagicMock()
        mock_response.text = mock_report

        with patch("src.agents.analyst.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            report = await orch.run_demo()

        assert report.brand == "Amul"
        assert report.category == "Dairy & Bread"

        # Verify data was seeded: 3 categories × 3 platforms × 10 products = 90
        count = orch.conn.execute("SELECT COUNT(*) FROM product_catalog").fetchone()[0]
        assert count == 90

        # Verify all 3 categories present
        cats = {r[0] for r in orch.conn.execute("SELECT DISTINCT category FROM product_catalog").fetchall()}
        assert cats == {"Dairy & Bread", "Fruits & Vegetables", "Snacks & Munchies"}


class TestCLIParsing:
    def test_scrape_morning_args(self) -> None:
        from analyze import build_parser

        parser = build_parser()
        args = parser.parse_args(["--scrape", "--morning"])
        assert args.scrape is True
        assert args.morning is True

    def test_scrape_night_args(self) -> None:
        from analyze import build_parser

        parser = build_parser()
        args = parser.parse_args(["--scrape", "--night"])
        assert args.scrape is True
        assert args.night is True

    def test_calculate_sales_args(self) -> None:
        from analyze import build_parser

        parser = build_parser()
        args = parser.parse_args(["--calculate-sales", "--date", "2026-02-27"])
        assert args.calculate_sales is True
        assert args.date == "2026-02-27"

    def test_normalize_args(self) -> None:
        from analyze import build_parser

        parser = build_parser()
        args = parser.parse_args(["--normalize", "--category", "Dairy & Bread"])
        assert args.normalize is True
        assert args.category == "Dairy & Bread"

    def test_analyze_args(self) -> None:
        from analyze import build_parser

        parser = build_parser()
        args = parser.parse_args(["--analyze", "--brand", "Amul", "--category", "Dairy & Bread"])
        assert args.analyze is True
        assert args.brand == "Amul"
        assert args.category == "Dairy & Bread"

    def test_demo_args(self) -> None:
        from analyze import build_parser

        parser = build_parser()
        args = parser.parse_args(["--demo"])
        assert args.demo is True

    def test_full_pipeline_args(self) -> None:
        from analyze import build_parser

        parser = build_parser()
        args = parser.parse_args(["--full-pipeline"])
        assert args.full_pipeline is True
