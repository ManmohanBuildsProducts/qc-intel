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


class TestCategoryLandscape:
    def test_landscape_returns_brands(self, client: TestClient) -> None:
        resp = client.get("/api/category/Dairy %26 Bread/landscape")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["category"] == "Dairy & Bread"
        assert data["total_brands"] >= 2
        assert data["total_skus"] == 3
        brands = data["brands"]
        names = [b["brand"] for b in brands]
        assert "Amul" in names
        assert "Mother Dairy" in names
        amul = next(b for b in brands if b["brand"] == "Amul")
        assert amul["sku_count"] == 2
        assert amul["avg_price"] > 0
        assert "platforms" in amul
        assert data["price_range"]["min"] > 0
        assert data["price_range"]["max"] >= data["price_range"]["min"]

    def test_landscape_avg_discount(self, client: TestClient) -> None:
        resp = client.get("/api/category/Dairy %26 Bread/landscape")
        data = resp.json()["data"]
        amul = next(b for b in data["brands"] if b["brand"] == "Amul")
        # Amul: price=29, mrp=30 → discount ~3.3%
        assert amul["avg_discount_pct"] > 0

    def test_landscape_empty_category(self, client: TestClient) -> None:
        resp = client.get("/api/category/Nonexistent/landscape")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_brands"] == 0
        assert data["total_skus"] == 0
        assert data["brands"] == []


class TestCategoryWhitespace:
    def test_whitespace_returns_price_bands(self, client: TestClient) -> None:
        resp = client.get("/api/category/Dairy %26 Bread/whitespace")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_skus"] == 3
        assert data["total_brands"] >= 2
        bands = data["price_bands"]
        assert len(bands) == 10
        for band in bands:
            assert "range" in band
            assert "sku_count" in band
            assert "brand_count" in band
            assert "density" in band
            assert band["density"] in ("sparse", "moderate", "crowded")

    def test_whitespace_empty_category(self, client: TestClient) -> None:
        resp = client.get("/api/category/Nonexistent/whitespace")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["price_bands"] == []
        assert data["total_skus"] == 0


class TestBrandMetrics:
    def test_brand_metrics_share_and_histogram(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        data = resp.json()["data"]
        share = data["share"]
        assert share["sku_count"] == 2
        assert share["category_total"] == 3
        assert share["share_pct"] > 0
        assert share["rank"] == 1  # Amul has 2 SKUs vs Mother Dairy's 1
        # Price histogram
        hist = data["price_histogram"]
        assert len(hist["labels"]) == 8
        assert len(hist["brand"]) == 8
        assert len(hist["category"]) == 8
        # MRP tiers
        tiers = data["mrp_tiers"]
        assert tiers["labels"] == ["Budget", "Mid", "Premium"]
        assert len(tiers["brand"]) == 3
        # Discount
        assert "brand_avg" in data["discount"]
        assert "category_avg" in data["discount"]
        # Platform coverage
        assert "by_platform" in data["platform_coverage"]
        # Competitors
        assert len(data["all_competitors"]) >= 2
        target = next(c for c in data["all_competitors"] if c["is_target"])
        assert target["brand"] == "Amul"

    def test_brand_metrics_unknown_brand(self, client: TestClient) -> None:
        resp = client.get("/api/brand/UnknownBrand/metrics?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["share"]["sku_count"] == 0
        assert data["share"]["share_pct"] == 0.0


class TestBrandScorecard:
    def test_scorecard_overview(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/scorecard")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["brand"] == "Amul"
        assert data["total_skus"] == 2
        assert data["category_count"] == 1
        assert data["platform_count"] == 2
        # Platform SKUs — all 3 platforms present in keys
        assert "blinkit" in data["platform_skus"]
        assert "zepto" in data["platform_skus"]
        assert "instamart" in data["platform_skus"]
        assert data["platform_skus"]["blinkit"] == 1
        assert data["platform_skus"]["zepto"] == 1
        assert data["platform_skus"]["instamart"] == 0
        # Categories detail
        cats = data["categories"]
        assert len(cats) == 1
        assert cats[0]["category"] == "Dairy & Bread"
        assert cats[0]["sku_count"] == 2
        assert cats[0]["share_pct"] > 0

    def test_scorecard_unknown_brand(self, client: TestClient) -> None:
        resp = client.get("/api/brand/NoBrand/scorecard")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_skus"] == 0
        assert data["categories"] == []


class TestBrandGaps:
    def test_gaps_matrix(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/gaps?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["brand"] == "Amul"
        assert data["category"] == "Dairy & Bread"
        matrix = data["platform_matrix"]
        assert len(matrix) >= 1
        # Each item has platform presence info
        for item in matrix:
            assert "product_name" in item
            assert "gap_count" in item
            for p in ("blinkit", "zepto", "instamart"):
                assert p in item
                assert "present" in item[p]
        summary = data["summary"]
        assert summary["total_products"] >= 1

    def test_gaps_unknown_brand(self, client: TestClient) -> None:
        resp = client.get("/api/brand/NoBrand/gaps?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["platform_matrix"] == []
        assert data["summary"]["total_products"] == 0


class TestDiscountBattle:
    def test_discount_battle_returns_brands(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/discount-battle?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        data = resp.json()["data"]
        brands = data["brands"]
        assert len(brands) >= 2
        names = [b["brand"] for b in brands]
        assert "Amul" in names
        amul = next(b for b in brands if b["brand"] == "Amul")
        assert amul["is_target"] is True
        assert "avg_discount_pct" in amul
        assert "discounted_sku_pct" in amul
        assert "category_avg_discount" in data

    def test_discount_battle_empty_category(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/discount-battle?category=Nonexistent")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["brands"] == []
        assert data["category_avg_discount"] == 0.0


class TestPlatformHeatmap:
    """Test brand metrics platform coverage acts as heatmap data source."""

    def test_platform_coverage_in_metrics(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread")
        assert resp.status_code == 200
        data = resp.json()["data"]
        coverage = data["platform_coverage"]
        assert coverage["total"] == 2
        assert "by_platform" in coverage
        assert coverage["by_platform"]["blinkit"] == 1
        assert coverage["by_platform"]["zepto"] == 1


class TestReports:
    def test_generate_report(self, client: TestClient) -> None:
        mock_response = MagicMock()
        mock_response.text = "## Executive Summary\nTest report content"

        with patch("src.agents.analyst.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
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
        """Unknown brand triggers opportunity analysis mode via Gemini."""
        mock_response = MagicMock()
        mock_response.text = "## Executive Summary\nOpportunity analysis for UnknownBrand."

        with patch("src.agents.analyst.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            resp = client.post(
                "/api/reports/generate",
                json={"brand": "UnknownBrand", "category": "Dairy & Bread"},
            )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["product_count"] == 0
        assert data["platform_count"] == 0
        assert data["is_opportunity_mode"] is True
        assert len(data["content"]) > 0
