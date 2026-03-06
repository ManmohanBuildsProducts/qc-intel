"""Tests for analytics agent — data preparation and report generation."""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.analyst import REPORT_SECTIONS, AnalyticsService
from src.agents.scraper.service import ScrapeService
from src.models.product import Platform, TimeOfDay


class TestPrepareReportData:
    def _seed_data(self, db_session, blinkit_data, zepto_data, instamart_data):
        service = ScrapeService(db_session)
        service.process_scrape_results(
            blinkit_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING,
        )
        service.process_scrape_results(
            zepto_data, Platform.ZEPTO, "122001", "Dairy & Bread", TimeOfDay.MORNING,
        )
        service.process_scrape_results(
            instamart_data, Platform.INSTAMART, "122001", "Dairy & Bread", TimeOfDay.MORNING,
        )

    def test_prepare_report_data(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data,
        zepto_fixture_data,
        instamart_fixture_data,
    ) -> None:
        self._seed_data(db_session, blinkit_fixture_data, zepto_fixture_data, instamart_fixture_data)

        analytics = AnalyticsService(db_session)
        data = analytics.prepare_report_data("Amul", "Dairy & Bread")

        assert data["brand"] == "Amul"
        assert data["category"] == "Dairy & Bread"
        assert data["brand_product_count"] > 0
        assert len(data["platforms_present"]) > 0
        assert data["total_category_products"] > 0
        assert len(data["competitor_brands"]) > 0

    def test_prepare_report_with_prices(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data,
        zepto_fixture_data,
        instamart_fixture_data,
    ) -> None:
        self._seed_data(db_session, blinkit_fixture_data, zepto_fixture_data, instamart_fixture_data)

        analytics = AnalyticsService(db_session)
        data = analytics.prepare_report_data("Amul", "Dairy & Bread")

        assert len(data["brand_prices"]) > 0
        first_price = data["brand_prices"][0]
        assert "price" in first_price
        assert "mrp" in first_price
        assert "platform" in first_price

    def test_empty_brand(self, db_session: sqlite3.Connection) -> None:
        analytics = AnalyticsService(db_session)
        data = analytics.prepare_report_data("NonexistentBrand", "Dairy & Bread")
        assert data["brand_product_count"] == 0
        assert len(data["brand_prices"]) == 0


class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_generate_report_structure(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data,
        zepto_fixture_data,
        instamart_fixture_data,
        tmp_path: Path,
    ) -> None:
        # Seed data
        service = ScrapeService(db_session)
        service.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING,
        )
        service.process_scrape_results(
            zepto_fixture_data, Platform.ZEPTO, "122001", "Dairy & Bread", TimeOfDay.MORNING,
        )
        service.process_scrape_results(
            instamart_fixture_data, Platform.INSTAMART, "122001", "Dairy & Bread", TimeOfDay.MORNING,
        )

        # Mock Claude response with all 8 sections
        mock_report = "\n\n".join([
            f"## {section}\n\nAnalysis for {section}." for section in REPORT_SECTIONS
        ])

        mock_response = MagicMock()
        mock_response.text = mock_report

        analytics = AnalyticsService(db_session)

        with patch("src.agents.analyst.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            report = await analytics.generate_report("Amul", "Dairy & Bread")

        assert report.brand == "Amul"
        assert report.category == "Dairy & Bread"
        assert report.sections == REPORT_SECTIONS
        assert report.product_count > 0
        assert report.platform_count > 0
        assert Path(report.report_path).exists()

    @pytest.mark.asyncio
    async def test_generate_empty_brand_report(self, db_session: sqlite3.Connection) -> None:
        analytics = AnalyticsService(db_session)
        report = await analytics.generate_report("NonexistentBrand", "Dairy & Bread")

        assert report.product_count == 0
        assert report.platform_count == 0
        assert Path(report.report_path).exists()
        content = Path(report.report_path).read_text()
        # Opportunity analysis mode: generates insights even with no brand data
        assert len(content) > 100


class TestReportSaving:
    def test_save_report(self, db_session: sqlite3.Connection) -> None:
        analytics = AnalyticsService(db_session)
        path = analytics._save_report("Amul", "Dairy & Bread", "# Test Report\n\nContent here.")
        assert Path(path).exists()
        assert "amul" in path.lower()
        content = Path(path).read_text()
        assert "# Test Report" in content


class TestFormatDataForGemini:
    def test_format_includes_brand_info(self, db_session: sqlite3.Connection) -> None:
        analytics = AnalyticsService(db_session)
        data = {
            "brand": "Amul",
            "category": "Dairy & Bread",
            "brand_product_count": 5,
            "platforms_present": ["blinkit", "zepto"],
            "total_category_products": 20,
            "competitor_brands": ["Mother Dairy", "Nestle"],
            "brand_prices": [],
            "competitor_prices": [],
            "cross_platform_products": [],
        }
        result = analytics._format_data_for_gemini(data)
        assert "Amul" in result
        assert "Dairy & Bread" in result
        assert "blinkit" in result
        assert "Mother Dairy" in result

    def test_format_includes_prices(self, db_session: sqlite3.Connection) -> None:
        analytics = AnalyticsService(db_session)
        data = {
            "brand": "Amul",
            "category": "Dairy & Bread",
            "brand_product_count": 1,
            "platforms_present": ["blinkit"],
            "total_category_products": 5,
            "competitor_brands": [],
            "brand_prices": [
                {"name": "Amul Milk", "platform": "blinkit", "price": 29.0, "mrp": 30.0, "in_stock": True},
            ],
            "competitor_prices": [
                {"name": "MD Milk", "brand": "Mother Dairy", "platform": "zepto", "price": 28.0, "mrp": 29.0},
            ],
            "cross_platform_products": [],
        }
        result = analytics._format_data_for_gemini(data)
        assert "29.0" in result
        assert "In Stock" in result
        assert "MD Milk" in result
