"""Tests for the brand metrics API endpoint."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.deps import get_db
from api.main import app
from src.db.init_db import init_db


@pytest.fixture()
def metrics_db(tmp_path: Path) -> sqlite3.Connection:
    """DB seeded with enough data to exercise all metrics queries."""
    db_path = str(tmp_path / "test_metrics.db")
    init_conn = init_db(db_path)
    init_conn.close()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    obs_sql = (
        "INSERT INTO product_observations"
        " (catalog_id, scrape_run_id, pincode, price, mrp, in_stock, max_cart_qty, time_of_day)"
        " VALUES (?, 'run-1', '122001', ?, ?, 1, 5, 'morning')"
    )
    cat_sql = (
        "INSERT INTO product_catalog"
        " (platform, platform_product_id, name, brand, category, unit)"
        " VALUES (?, ?, ?, ?, 'Dairy & Bread', '500ml')"
    )

    # Amul — on both platforms, varying prices
    conn.execute(cat_sql, ("blinkit", "b-amul-1", "Amul Taaza Milk", "Amul"))      # id=1
    conn.execute(cat_sql, ("zepto",   "z-amul-1", "Amul Taaza Milk 500ml", "Amul")) # id=2
    conn.execute(cat_sql, ("blinkit", "b-amul-2", "Amul Gold Milk", "Amul"))        # id=3
    conn.execute(cat_sql, ("zepto",   "z-amul-2", "Amul Gold Milk 500ml", "Amul"))  # id=4
    conn.execute(cat_sql, ("blinkit", "b-amul-3", "Amul Butter 100g", "Amul"))      # id=5

    # Mother Dairy — blinkit only
    conn.execute(cat_sql, ("blinkit", "b-md-1", "Mother Dairy Milk 500ml", "Mother Dairy"))  # id=6
    conn.execute(cat_sql, ("blinkit", "b-md-2", "Mother Dairy Curd 400g", "Mother Dairy"))   # id=7

    # Britannia — zepto only
    conn.execute(cat_sql, ("zepto", "z-brit-1", "Britannia Cheese 200g", "Britannia"))  # id=8

    # Observations (price, mrp)
    conn.execute(obs_sql, (1, 29.0, 30.0))   # Amul Taaza blinkit
    conn.execute(obs_sql, (2, 31.0, 30.0))   # Amul Taaza zepto — higher price (parity delta)
    conn.execute(obs_sql, (3, 69.0, 75.0))   # Amul Gold blinkit
    conn.execute(obs_sql, (4, 69.0, 75.0))   # Amul Gold zepto — same price (no parity delta)
    conn.execute(obs_sql, (5, 56.0, 57.0))   # Amul Butter
    conn.execute(obs_sql, (6, 28.0, 30.0))   # MD Milk
    conn.execute(obs_sql, (7, 40.0, 42.0))   # MD Curd
    conn.execute(obs_sql, (8, 110.0, 130.0)) # Britannia Cheese — big discount

    # Canonical products + mappings for parity test
    conn.execute(
        "INSERT INTO canonical_products (canonical_name, brand, category, unit_normalized)"
        " VALUES ('Amul Taaza Milk', 'Amul', 'Dairy & Bread', '500ml')"  # id=1
    )
    conn.execute(
        "INSERT INTO canonical_products (canonical_name, brand, category, unit_normalized)"
        " VALUES ('Amul Gold Milk', 'Amul', 'Dairy & Bread', '500ml')"  # id=2
    )
    conn.execute(
        "INSERT INTO product_mappings (catalog_id, canonical_id, similarity_score)"
        " VALUES (1, 1, 1.0)"  # blinkit Amul Taaza → canonical 1
    )
    conn.execute(
        "INSERT INTO product_mappings (catalog_id, canonical_id, similarity_score)"
        " VALUES (2, 1, 0.95)"  # zepto Amul Taaza → canonical 1
    )
    conn.execute(
        "INSERT INTO product_mappings (catalog_id, canonical_id, similarity_score)"
        " VALUES (3, 2, 1.0)"  # blinkit Amul Gold → canonical 2
    )
    conn.execute(
        "INSERT INTO product_mappings (catalog_id, canonical_id, similarity_score)"
        " VALUES (4, 2, 0.95)"  # zepto Amul Gold → canonical 2
    )
    conn.execute(
        "INSERT INTO scrape_runs (id, platform, pincode, category, time_of_day, started_at, status)"
        " VALUES ('run-1', 'blinkit', '122001', 'Dairy & Bread', 'morning', '2025-01-15T08:00:00', 'completed')"
    )
    conn.commit()
    return conn


@pytest.fixture()
def client(metrics_db: sqlite3.Connection) -> TestClient:
    def override():
        yield metrics_db

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestMetricsEndpoint:
    def test_returns_200_for_known_brand(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread")
        assert resp.status_code == 200

    def test_response_has_all_sections(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        assert "share" in data
        assert "price_histogram" in data
        assert "mrp_tiers" in data
        assert "discount" in data
        assert "platform_coverage" in data
        assert "price_parity" in data
        assert "all_competitors" in data
        assert "canonical_competitors" in data

    def test_share_sku_count(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        assert data["share"]["sku_count"] == 5  # Amul has 5 SKUs
        assert data["share"]["category_total"] == 8
        assert data["share"]["rank"] == 1  # Amul has most SKUs

    def test_share_percentage(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        share_pct = data["share"]["share_pct"]
        assert abs(share_pct - 62.5) < 0.1  # 5/8 = 62.5%

    def test_price_histogram_has_8_buckets(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        hist = data["price_histogram"]
        assert len(hist["labels"]) == 8
        assert len(hist["brand"]) == 8
        assert len(hist["category"]) == 8

    def test_price_histogram_brand_sums_to_sku_count(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        hist = data["price_histogram"]
        # Brand bucket counts should sum to Amul's SKU count (5)
        assert sum(hist["brand"]) == 5

    def test_mrp_tiers_brand_sums_to_sku_count(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        tiers = data["mrp_tiers"]
        assert sum(tiers["brand"]) == 5

    def test_mrp_tiers_has_boundaries(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        tiers = data["mrp_tiers"]
        assert "budget_threshold" in tiers
        assert "premium_threshold" in tiers
        assert tiers["budget_threshold"] < tiers["premium_threshold"]

    def test_discount_brand_avg(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        # Amul discounts: 29/30=3.3%, 31/30 (no disc), 69/75=8%, 69/75=8%, 56/57=1.75%
        # Mean of discounts on SKUs with mrp > price: roughly positive avg
        assert "brand_avg" in data["discount"]
        assert "category_avg" in data["discount"]

    def test_platform_coverage(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        cov = data["platform_coverage"]
        assert cov["by_platform"]["blinkit"] == 3  # b-amul-1, b-amul-2, b-amul-3
        assert cov["by_platform"]["zepto"] == 2    # z-amul-1, z-amul-2
        assert cov["cross_platform_count"] == 2   # canonical 1 + canonical 2

    def test_price_parity_only_shows_delta(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        parity = data["price_parity"]
        # Only canonical 1 (Amul Taaza) has a delta (29 vs 31)
        # canonical 2 (Amul Gold) has same price on both → excluded
        assert len(parity) == 1
        row = parity[0]
        assert abs(row["delta"]) == 2.0
        assert "blinkit_price" in row
        assert "zepto_price" in row
        assert "delta_pct" in row

    def test_all_competitors_includes_target_brand(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        competitors = data["all_competitors"]
        names = [c["brand"] for c in competitors]
        assert "Amul" in names
        amul = next(c for c in competitors if c["brand"] == "Amul")
        assert amul["is_target"] is True
        assert amul["sku_count"] == 5

    def test_all_competitors_sorted_by_sku_count(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        competitors = data["all_competitors"]
        counts = [c["sku_count"] for c in competitors]
        assert counts == sorted(counts, reverse=True)

    def test_canonical_competitors(self, client: TestClient) -> None:
        data = client.get("/api/brand/Amul/metrics?category=Dairy+%26+Bread").json()["data"]
        # No other brand shares canonical clusters with Amul in test data
        assert isinstance(data["canonical_competitors"], list)

    def test_unknown_brand_returns_zeros(self, client: TestClient) -> None:
        data = client.get("/api/brand/NoSuchBrand/metrics?category=Dairy+%26+Bread").json()["data"]
        assert data["share"]["sku_count"] == 0
        assert data["platform_coverage"]["total"] == 0
        assert data["price_parity"] == []
        assert data["canonical_competitors"] == []

    def test_missing_category_param_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/brand/Amul/metrics")
        assert resp.status_code == 422
