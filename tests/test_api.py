"""Tests for the FastAPI backend."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.deps import get_db
from api.main import app
from src.db.init_db import init_db


@pytest.fixture()
def seeded_db(tmp_path: Path) -> sqlite3.Connection:
    """Initialize DB and seed with sample data."""
    db_path = str(tmp_path / "test_api.db")
    # init_db creates schema, then we reopen with check_same_thread=False
    # so the connection can be shared between test thread and FastAPI threadpool
    init_conn = init_db(db_path)
    init_conn.close()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Seed catalog
    conn.execute(
        "INSERT INTO product_catalog (platform, platform_product_id, name, brand, category, unit) "
        "VALUES ('blinkit', 'b-1', 'Amul Taaza Milk 500ml', 'Amul', 'Dairy & Bread', '500ml')"
    )
    conn.execute(
        "INSERT INTO product_catalog (platform, platform_product_id, name, brand, category, unit) "
        "VALUES ('zepto', 'z-1', 'Amul Taaza Toned Milk 500ml', 'Amul', 'Dairy & Bread', '500ml')"
    )
    conn.execute(
        "INSERT INTO product_catalog (platform, platform_product_id, name, brand, category, unit) "
        "VALUES ('instamart', 'i-1', 'Mother Dairy Full Cream 500ml', 'Mother Dairy', 'Dairy & Bread', '500ml')"
    )
    conn.execute(
        "INSERT INTO product_catalog (platform, platform_product_id, name, brand, category, unit) "
        "VALUES ('blinkit', 'b-2', 'Lays Classic Salted 52g', 'Lays', 'Snacks & Munchies', '52g')"
    )

    # Seed observations
    obs_sql = (
        "INSERT INTO product_observations"
        " (catalog_id, scrape_run_id, pincode, price, mrp, in_stock, max_cart_qty, time_of_day)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    conn.execute(obs_sql, (1, "run-1", "122001", 29.0, 30.0, 1, 5, "morning"))
    conn.execute(obs_sql, (2, "run-1", "122001", 29.0, 30.0, 1, 5, "morning"))
    conn.execute(obs_sql, (3, "run-1", "122001", 32.0, 33.0, 1, 5, "morning"))
    conn.execute(obs_sql, (4, "run-1", "122001", 20.0, 20.0, 0, 0, "morning"))

    # Seed scrape run
    conn.execute(
        "INSERT INTO scrape_runs (id, platform, pincode, category, time_of_day, started_at, status) "
        "VALUES ('run-1', 'blinkit', '122001', 'Dairy & Bread', 'morning', '2025-01-15T08:00:00', 'completed')"
    )
    conn.commit()
    return conn


@pytest.fixture()
def client(seeded_db: sqlite3.Connection) -> TestClient:
    """TestClient with overridden DB dependency."""

    def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestHealth:
    def test_health(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestBrands:
    def test_list_brands(self, client: TestClient) -> None:
        resp = client.get("/api/brands")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data, list)
        assert len(data) >= 1
        names = [b["name"] for b in data]
        assert "Amul" in names
        # Check structure
        amul = next(b for b in data if b["name"] == "Amul")
        assert amul["product_count"] == 2
        assert "categories" in amul


class TestCategories:
    def test_list_categories(self, client: TestClient) -> None:
        resp = client.get("/api/categories")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data, list)
        names = [c["name"] for c in data]
        assert "Dairy & Bread" in names
        dairy = next(c for c in data if c["name"] == "Dairy & Bread")
        assert dairy["product_count"] == 3
        assert dairy["brand_count"] >= 2


class TestProducts:
    def test_list_all_products(self, client: TestClient) -> None:
        resp = client.get("/api/products")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert body["meta"]["total"] == 4

    def test_filter_by_brand(self, client: TestClient) -> None:
        resp = client.get("/api/products?brand=Amul")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2
        for item in body["data"]:
            assert item["brand"] == "Amul"

    def test_filter_by_category(self, client: TestClient) -> None:
        resp = client.get("/api/products?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 3

    def test_filter_by_platform(self, client: TestClient) -> None:
        resp = client.get("/api/products?platform=blinkit")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["total"] == 2

    def test_pagination(self, client: TestClient) -> None:
        resp = client.get("/api/products?per_page=2&page=1")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["meta"]["page"] == 1
        assert body["meta"]["per_page"] == 2

    def test_product_has_price(self, client: TestClient) -> None:
        resp = client.get("/api/products?brand=Amul")
        body = resp.json()
        item = body["data"][0]
        assert "price" in item
        assert item["price"] is not None


class TestDashboardStats:
    def test_stats(self, client: TestClient) -> None:
        resp = client.get("/api/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["products"] == 4
        assert data["brands"] >= 3
        assert data["categories"] == 2
        assert data["platforms"] == 3
        assert data["last_scrape"] is not None


class TestCharts:
    def test_price_distribution(self, client: TestClient) -> None:
        resp = client.get("/api/charts/price-distribution?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        chart = resp.json()["data"]
        assert "labels" in chart
        assert "datasets" in chart
        assert len(chart["labels"]) == 5  # 5 price buckets

    def test_platform_coverage(self, client: TestClient) -> None:
        resp = client.get("/api/charts/platform-coverage?brand=Amul")
        assert resp.status_code == 200
        chart = resp.json()["data"]
        assert "labels" in chart
        assert "datasets" in chart
        assert len(chart["datasets"]) == 1

    def test_brand_share(self, client: TestClient) -> None:
        resp = client.get("/api/charts/brand-share?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        chart = resp.json()["data"]
        assert "labels" in chart
        names = chart["labels"]
        assert "Amul" in names

    def test_empty_category_returns_empty(self, client: TestClient) -> None:
        resp = client.get("/api/charts/brand-share?category=Nonexistent")
        assert resp.status_code == 200
        chart = resp.json()["data"]
        assert chart["labels"] == []
        assert chart["datasets"][0]["data"] == []


class TestReports:
    def test_generate_report(self, client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="## Executive Summary\nTest report content")]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)

        with patch("src.agents.analyst.anthropic.AsyncAnthropic", return_value=mock_client):
            resp = client.post(
                "/api/reports/generate",
                json={"brand": "Amul", "category": "Dairy & Bread"},
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["brand"] == "Amul"
        assert data["category"] == "Dairy & Bread"
        assert "content" in data
        assert len(data["content"]) > 0
        assert data["sections"] == [
            "Executive Summary",
            "Brand Overview",
            "Price Analysis",
            "Competitive Landscape",
            "Cross-Platform Availability",
            "Sales Velocity",
            "White Space Analysis",
            "Recommendations",
        ]

    def test_generate_report_no_data(self, client: TestClient) -> None:
        """Report for unknown brand should still return 200 with empty-data report."""
        resp = client.post(
            "/api/reports/generate",
            json={"brand": "UnknownBrand", "category": "Dairy & Bread"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["product_count"] == 0
        assert data["platform_count"] == 0
        assert "No data available" in data["content"]
