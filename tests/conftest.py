"""Shared test fixtures for QC Intel tests."""

import json
import sqlite3
from pathlib import Path

import pytest

from src.db.init_db import init_db
from src.models.product import (
    CatalogProduct,
    Platform,
    ProductObservation,
    ScrapedProduct,
    TimeOfDay,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Temporary database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def db_session(db_path: str) -> sqlite3.Connection:
    """Initialized database connection for testing."""
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def blinkit_fixture_data() -> list[dict]:
    """Raw Blinkit fixture data."""
    return json.loads((FIXTURES_DIR / "blinkit_dairy.json").read_text())


@pytest.fixture
def zepto_fixture_data() -> list[dict]:
    """Raw Zepto fixture data."""
    return json.loads((FIXTURES_DIR / "zepto_dairy.json").read_text())


@pytest.fixture
def instamart_fixture_data() -> list[dict]:
    """Raw Instamart fixture data."""
    return json.loads((FIXTURES_DIR / "instamart_dairy.json").read_text())


@pytest.fixture
def sample_scraped_products() -> list[ScrapedProduct]:
    """Sample ScrapedProduct instances for testing."""
    return [
        ScrapedProduct(
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
        ),
        ScrapedProduct(
            platform=Platform.ZEPTO,
            platform_product_id="z-31001",
            name="Amul Taaza Toned Milk",
            brand="Amul",
            category="Dairy & Bread",
            unit="500 ml",
            price=29.0,
            mrp=30.0,
            in_stock=True,
            max_cart_qty=5,
        ),
        ScrapedProduct(
            platform=Platform.INSTAMART,
            platform_product_id="im-5001",
            name="Amul Taaza Homogenised Toned Milk",
            brand="Amul",
            category="Dairy & Bread",
            unit="500 ml",
            price=29.0,
            mrp=30.0,
            in_stock=True,
            max_cart_qty=5,
        ),
    ]


@pytest.fixture
def sample_catalog_products() -> list[CatalogProduct]:
    """Sample CatalogProduct instances across all 3 platforms."""
    return [
        CatalogProduct(
            platform=Platform.BLINKIT,
            platform_product_id="39868",
            name="Amul Taaza Toned Fresh Milk",
            brand="Amul",
            category="Dairy & Bread",
            unit="500ml",
        ),
        CatalogProduct(
            platform=Platform.ZEPTO,
            platform_product_id="z-31001",
            name="Amul Taaza Toned Milk",
            brand="Amul",
            category="Dairy & Bread",
            unit="500 ml",
        ),
        CatalogProduct(
            platform=Platform.INSTAMART,
            platform_product_id="im-5001",
            name="Amul Taaza Homogenised Toned Milk",
            brand="Amul",
            category="Dairy & Bread",
            unit="500 ml",
        ),
    ]


@pytest.fixture
def sample_observations() -> list[ProductObservation]:
    """Sample observations for morning/night pairs."""
    return [
        ProductObservation(
            catalog_id=1,
            scrape_run_id="run-morning",
            pincode="122001",
            price=29.0,
            max_cart_qty=20,
            time_of_day=TimeOfDay.MORNING,
        ),
        ProductObservation(
            catalog_id=1,
            scrape_run_id="run-night",
            pincode="122001",
            price=29.0,
            max_cart_qty=5,
            time_of_day=TimeOfDay.NIGHT,
        ),
    ]
