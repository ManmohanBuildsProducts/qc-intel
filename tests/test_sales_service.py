"""Integration tests for SalesService with real DB."""

import sqlite3
from datetime import datetime

from src.agents.scraper.sales_service import SalesService
from src.db.repository import CatalogRepository, ObservationRepository
from src.models.product import CatalogProduct, Platform, ProductObservation, TimeOfDay


def _seed_product(catalog_repo: CatalogRepository, brand: str = "Amul", name: str = "Amul Taaza Milk") -> int:
    """Insert a catalog product and return its id."""
    return catalog_repo.upsert_product(
        CatalogProduct(
            platform=Platform.BLINKIT,
            platform_product_id=f"prod-{name.replace(' ', '-').lower()}",
            name=name,
            brand=brand,
            category="Dairy & Bread",
            unit="500ml",
        )
    )


def _seed_observations(
    obs_repo: ObservationRepository,
    catalog_id: int,
    morning_qty: int,
    night_qty: int,
    pincode: str = "122001",
) -> None:
    """Insert a morning/night observation pair for today."""
    obs_repo.insert_observation(
        ProductObservation(
            catalog_id=catalog_id,
            scrape_run_id="run-morning-001",
            pincode=pincode,
            price=29.0,
            max_cart_qty=morning_qty,
            time_of_day=TimeOfDay.MORNING,
        )
    )
    obs_repo.insert_observation(
        ProductObservation(
            catalog_id=catalog_id,
            scrape_run_id="run-night-001",
            pincode=pincode,
            price=29.0,
            max_cart_qty=night_qty,
            time_of_day=TimeOfDay.NIGHT,
        )
    )


class TestCalculateDailySales:
    def test_calculate_daily_sales(self, db_session: sqlite3.Connection) -> None:
        """Morning=20, Night=5 should produce 15 estimated sales with high confidence."""
        catalog_repo = CatalogRepository(db_session)
        obs_repo = ObservationRepository(db_session)

        product_id = _seed_product(catalog_repo)
        _seed_observations(obs_repo, product_id, morning_qty=20, night_qty=5)

        service = SalesService(db_session)
        today = datetime.now().strftime("%Y-%m-%d")
        result = service.calculate_daily_sales(today)

        assert result["records_created"] == 1
        assert result["total_estimated_sales"] == 15
        assert result["by_confidence"].get("high", 0) == 1


class TestCategorySalesSummary:
    def test_category_sales_summary(self, db_session: sqlite3.Connection) -> None:
        """Multiple brands should return summaries ordered by total_sales DESC."""
        catalog_repo = CatalogRepository(db_session)
        obs_repo = ObservationRepository(db_session)

        # Amul product: delta = 20 - 5 = 15
        amul_id = _seed_product(catalog_repo, brand="Amul", name="Amul Taaza Milk")
        _seed_observations(obs_repo, amul_id, morning_qty=20, night_qty=5)

        # Mother Dairy product: delta = 30 - 2 = 28
        md_id = _seed_product(catalog_repo, brand="Mother Dairy", name="Mother Dairy Full Cream Milk")
        _seed_observations(obs_repo, md_id, morning_qty=30, night_qty=2)

        service = SalesService(db_session)
        today = datetime.now().strftime("%Y-%m-%d")
        service.calculate_daily_sales(today)

        summary = service.get_category_sales_summary("Dairy & Bread", today)

        assert len(summary) == 2
        # Mother Dairy has higher sales (28 > 15), should be first
        assert summary[0]["brand"] == "Mother Dairy"
        assert summary[0]["total_estimated_sales"] == 28
        assert summary[1]["brand"] == "Amul"
        assert summary[1]["total_estimated_sales"] == 15


class TestNoObservations:
    def test_no_observations(self, db_session: sqlite3.Connection) -> None:
        """Empty DB should produce zero records and zero sales."""
        service = SalesService(db_session)
        today = datetime.now().strftime("%Y-%m-%d")
        result = service.calculate_daily_sales(today)

        assert result["records_created"] == 0
        assert result["total_estimated_sales"] == 0


class TestRestockDetection:
    def test_restock_detection(self, db_session: sqlite3.Connection) -> None:
        """Night > morning (restock) should produce low confidence."""
        catalog_repo = CatalogRepository(db_session)
        obs_repo = ObservationRepository(db_session)

        product_id = _seed_product(catalog_repo)
        _seed_observations(obs_repo, product_id, morning_qty=5, night_qty=15)

        service = SalesService(db_session)
        today = datetime.now().strftime("%Y-%m-%d")
        result = service.calculate_daily_sales(today)

        assert result["records_created"] == 1
        assert result["by_confidence"].get("low", 0) == 1
