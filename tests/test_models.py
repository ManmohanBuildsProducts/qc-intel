"""Tests for Pydantic models and exceptions — covers R7 (typed contracts)."""

import pytest

from src.models.exceptions import (
    AnalyticsError,
    ConfigError,
    DatabaseError,
    NormalizationError,
    QCIntelError,
    ScrapeError,
)
from src.models.product import (
    Confidence,
    Platform,
    ProductMapping,
    ProductObservation,
    SalesEstimate,
    ScrapedProduct,
    ScrapeRun,
    ScrapeRunStatus,
    TimeOfDay,
)


class TestScrapedProduct:
    def test_valid_product(self) -> None:
        p = ScrapedProduct(
            platform=Platform.BLINKIT,
            platform_product_id="39868",
            name="Amul Taaza Toned Fresh Milk",
            brand="Amul",
            category="Dairy & Bread",
            unit="500ml",
            price=29.0,
            mrp=30.0,
            in_stock=True,
            max_cart_qty=5,
        )
        assert p.platform == Platform.BLINKIT
        assert p.price == 29.0
        assert p.max_cart_qty == 5

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            ScrapedProduct(
                platform=Platform.ZEPTO,
                platform_product_id="1",
                name="Test",
                category="Test",
                price=-10.0,
            )

    def test_zero_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            ScrapedProduct(
                platform=Platform.ZEPTO,
                platform_product_id="1",
                name="Test",
                category="Test",
                price=0,
            )

    def test_negative_max_cart_qty_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_cart_qty must be non-negative"):
            ScrapedProduct(
                platform=Platform.BLINKIT,
                platform_product_id="1",
                name="Test",
                category="Test",
                price=10.0,
                max_cart_qty=-1,
            )

    def test_defaults(self) -> None:
        p = ScrapedProduct(
            platform=Platform.INSTAMART,
            platform_product_id="1",
            name="Test",
            category="Test",
            price=10.0,
        )
        assert p.in_stock is True
        assert p.max_cart_qty == 0
        assert p.brand is None
        assert p.raw_json is None

    def test_all_platforms(self) -> None:
        for platform in Platform:
            p = ScrapedProduct(
                platform=platform,
                platform_product_id="1",
                name="Test",
                category="Test",
                price=10.0,
            )
            assert p.platform == platform


class TestProductObservation:
    def test_valid_observation(self) -> None:
        obs = ProductObservation(
            catalog_id=1,
            scrape_run_id="run-001",
            pincode="122001",
            price=29.0,
            max_cart_qty=5,
            time_of_day=TimeOfDay.MORNING,
        )
        assert obs.pincode == "122001"
        assert obs.time_of_day == TimeOfDay.MORNING

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            ProductObservation(
                catalog_id=1,
                scrape_run_id="run-001",
                pincode="122001",
                price=-5.0,
                time_of_day=TimeOfDay.NIGHT,
            )


class TestSalesEstimate:
    def test_high_confidence(self) -> None:
        s = SalesEstimate(
            catalog_id=1,
            pincode="122001",
            sale_date="2026-02-27",
            morning_qty=20,
            night_qty=5,
            estimated_sales=15,
            confidence=Confidence.HIGH,
        )
        assert s.estimated_sales == 15
        assert s.confidence == Confidence.HIGH
        assert s.restock_flag is False

    def test_restock_flag(self) -> None:
        s = SalesEstimate(
            catalog_id=1,
            pincode="122001",
            sale_date="2026-02-27",
            morning_qty=5,
            night_qty=15,
            estimated_sales=0,
            confidence=Confidence.LOW,
            restock_flag=True,
        )
        assert s.restock_flag is True
        assert s.confidence == Confidence.LOW


class TestProductMapping:
    def test_valid_mapping(self) -> None:
        m = ProductMapping(
            catalog_id=1,
            canonical_id=1,
            similarity_score=0.92,
        )
        assert m.similarity_score == 0.92

    def test_score_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="similarity_score must be between 0 and 1"):
            ProductMapping(catalog_id=1, canonical_id=1, similarity_score=1.5)

    def test_negative_score(self) -> None:
        with pytest.raises(ValueError, match="similarity_score must be between 0 and 1"):
            ProductMapping(catalog_id=1, canonical_id=1, similarity_score=-0.1)


class TestScrapeRun:
    def test_default_status(self) -> None:
        r = ScrapeRun(
            id="run-001",
            platform=Platform.BLINKIT,
            pincode="122001",
            category="Dairy & Bread",
            time_of_day=TimeOfDay.MORNING,
        )
        assert r.status == ScrapeRunStatus.RUNNING
        assert r.products_found == 0
        assert r.errors == 0


class TestExceptions:
    def test_hierarchy(self) -> None:
        assert issubclass(ScrapeError, QCIntelError)
        assert issubclass(NormalizationError, QCIntelError)
        assert issubclass(AnalyticsError, QCIntelError)
        assert issubclass(DatabaseError, QCIntelError)
        assert issubclass(ConfigError, QCIntelError)

    def test_scrape_error_message(self) -> None:
        err = ScrapeError("blinkit", "timeout after 30s")
        assert "[blinkit]" in str(err)
        assert err.platform == "blinkit"

    def test_catch_as_base(self) -> None:
        with pytest.raises(QCIntelError):
            raise ScrapeError("zepto", "blocked")
