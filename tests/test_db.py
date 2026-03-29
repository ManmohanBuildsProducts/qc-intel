"""Tests for database init and repository — covers R4 (sales storage), R5 (daily tracking)."""

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src.db.init_db import EXPECTED_TABLES, init_db
from src.db.repository import (
    CanonicalRepository,
    CatalogRepository,
    ObservationRepository,
    SalesRepository,
    ScrapeRunRepository,
)
from src.models.product import (
    CanonicalProduct,
    CatalogProduct,
    Confidence,
    Platform,
    ProductMapping,
    ProductObservation,
    ScrapeRun,
    ScrapeRunStatus,
    TimeOfDay,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture
def db_conn(db_path: str) -> sqlite3.Connection:
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestInitDb:
    def test_creates_all_tables(self, db_conn: sqlite3.Connection) -> None:
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert tables == EXPECTED_TABLES

    def test_idempotent(self, db_path: str) -> None:
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        cursor = conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert tables == EXPECTED_TABLES
        conn2.close()

    def test_wal_mode(self, db_conn: sqlite3.Connection) -> None:
        mode = db_conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_foreign_keys_on(self, db_conn: sqlite3.Connection) -> None:
        fk = db_conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1

    def test_creates_data_directory(self, tmp_path: Path) -> None:
        nested = str(tmp_path / "sub" / "dir" / "test.db")
        conn = init_db(nested)
        assert Path(nested).exists()
        conn.close()

    def test_indexes_created(self, db_conn: sqlite3.Connection) -> None:
        cursor = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_catalog_platform" in indexes
        assert "idx_obs_unique" in indexes
        assert "idx_sales_date" in indexes
        assert len(indexes) >= 12


class TestSchemaConstraints:
    def test_catalog_platform_check(self, db_conn: sqlite3.Connection) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO product_catalog (platform, platform_product_id, name, category) "
                "VALUES ('invalid', '1', 'Test', 'Test')"
            )

    def test_catalog_unique_platform_product(self, db_conn: sqlite3.Connection) -> None:
        db_conn.execute(
            "INSERT INTO product_catalog (platform, platform_product_id, name, category) "
            "VALUES ('blinkit', '100', 'Milk', 'Dairy')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO product_catalog (platform, platform_product_id, name, category) "
                "VALUES ('blinkit', '100', 'Milk 2', 'Dairy')"
            )
        db_conn.rollback()

    def test_observation_time_of_day_check(self, db_conn: sqlite3.Connection) -> None:
        # Insert a catalog product first
        db_conn.execute(
            "INSERT INTO product_catalog (platform, platform_product_id, name, category) "
            "VALUES ('blinkit', '1', 'Test', 'Dairy')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO product_observations (catalog_id, scrape_run_id, pincode, price, time_of_day) "
                "VALUES (1, 'run1', '122001', 29.0, 'afternoon')"
            )
        db_conn.rollback()

    def test_sales_confidence_check(self, db_conn: sqlite3.Connection) -> None:
        db_conn.execute(
            "INSERT INTO product_catalog (platform, platform_product_id, name, category) "
            "VALUES ('blinkit', '1', 'Test', 'Dairy')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO daily_sales (catalog_id, pincode, sale_date,"
                " morning_qty, night_qty, estimated_sales, confidence) "
                "VALUES (1, '122001', '2026-02-27', 20, 5, 15, 'invalid')"
            )
        db_conn.rollback()

    def test_daily_sales_unique(self, db_conn: sqlite3.Connection) -> None:
        db_conn.execute(
            "INSERT INTO product_catalog (platform, platform_product_id, name, category) "
            "VALUES ('blinkit', '1', 'Test', 'Dairy')"
        )
        db_conn.execute(
            "INSERT INTO daily_sales (catalog_id, pincode, sale_date,"
            " morning_qty, night_qty, estimated_sales, confidence) "
            "VALUES (1, '122001', '2026-02-27', 20, 5, 15, 'high')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO daily_sales (catalog_id, pincode, sale_date,"
                " morning_qty, night_qty, estimated_sales, confidence) "
                "VALUES (1, '122001', '2026-02-27', 18, 3, 15, 'high')"
            )
        db_conn.rollback()


class TestCatalogRepository:
    def test_upsert_and_retrieve(self, db_conn: sqlite3.Connection) -> None:
        repo = CatalogRepository(db_conn)
        product = CatalogProduct(
            platform=Platform.BLINKIT,
            platform_product_id="39868",
            name="Amul Taaza Toned Fresh Milk",
            brand="Amul",
            category="Dairy & Bread",
            unit="500ml",
        )
        pid = repo.upsert_product(product)
        assert pid > 0

        retrieved = repo.get_by_id(pid)
        assert retrieved is not None
        assert retrieved.name == "Amul Taaza Toned Fresh Milk"
        assert retrieved.brand == "Amul"
        assert retrieved.platform == Platform.BLINKIT

    def test_upsert_updates_not_duplicates(self, db_conn: sqlite3.Connection) -> None:
        repo = CatalogRepository(db_conn)
        product = CatalogProduct(
            platform=Platform.BLINKIT,
            platform_product_id="39868",
            name="Amul Taaza",
            brand="Amul",
            category="Dairy & Bread",
        )
        pid1 = repo.upsert_product(product)

        product_updated = CatalogProduct(
            platform=Platform.BLINKIT,
            platform_product_id="39868",
            name="Amul Taaza Toned Fresh Milk 500ml",
            brand="Amul",
            category="Dairy & Bread",
        )
        pid2 = repo.upsert_product(product_updated)
        assert pid1 == pid2

        retrieved = repo.get_by_id(pid1)
        assert retrieved.name == "Amul Taaza Toned Fresh Milk 500ml"

    def test_get_by_platform(self, db_conn: sqlite3.Connection) -> None:
        repo = CatalogRepository(db_conn)
        for i, platform in enumerate(Platform):
            repo.upsert_product(CatalogProduct(
                platform=platform,
                platform_product_id=str(i),
                name=f"Product {i}",
                category="Dairy",
            ))
        blinkit = repo.get_by_platform(Platform.BLINKIT)
        assert len(blinkit) == 1

    def test_get_by_brand(self, db_conn: sqlite3.Connection) -> None:
        repo = CatalogRepository(db_conn)
        repo.upsert_product(CatalogProduct(
            platform=Platform.BLINKIT, platform_product_id="1",
            name="Amul Milk", brand="Amul", category="Dairy",
        ))
        repo.upsert_product(CatalogProduct(
            platform=Platform.BLINKIT, platform_product_id="2",
            name="Mother Dairy Milk", brand="Mother Dairy", category="Dairy",
        ))
        amul = repo.get_by_brand("Amul")
        assert len(amul) == 1
        assert amul[0].brand == "Amul"


class TestObservationRepository:
    def _insert_catalog(self, db_conn: sqlite3.Connection) -> int:
        repo = CatalogRepository(db_conn)
        return repo.upsert_product(CatalogProduct(
            platform=Platform.BLINKIT, platform_product_id="1",
            name="Test Milk", brand="Test", category="Dairy",
        ))

    def test_insert_and_retrieve(self, db_conn: sqlite3.Connection) -> None:
        cat_id = self._insert_catalog(db_conn)
        repo = ObservationRepository(db_conn)
        obs = ProductObservation(
            catalog_id=cat_id,
            scrape_run_id="run-001",
            pincode="122001",
            price=29.0,
            max_cart_qty=5,
            time_of_day=TimeOfDay.MORNING,
        )
        oid = repo.insert_observation(obs)
        assert oid > 0

        latest = repo.get_latest_for_product(cat_id, "122001")
        assert latest is not None
        assert latest.price == 29.0
        assert latest.max_cart_qty == 5


class TestSalesRepository:
    def _setup_morning_night(self, db_conn: sqlite3.Connection, morning_qty: int, night_qty: int) -> int:
        cat_repo = CatalogRepository(db_conn)
        cat_id = cat_repo.upsert_product(CatalogProduct(
            platform=Platform.BLINKIT, platform_product_id="1",
            name="Test Milk", brand="Test", category="Dairy",
        ))
        obs_repo = ObservationRepository(db_conn)
        obs_repo.insert_observation(ProductObservation(
            catalog_id=cat_id, scrape_run_id="run-m",
            pincode="122001", price=29.0,
            max_cart_qty=1, inventory_count=morning_qty,
            time_of_day=TimeOfDay.MORNING,
        ))
        db_conn.execute(
            """
            INSERT INTO product_observations
                (catalog_id, scrape_run_id, pincode, price, max_cart_qty,
                 inventory_count, time_of_day, observed_at)
            VALUES (?, 'run-n', '122001', 29.0, 1, ?, 'night', datetime('now'))
            """,
            (cat_id, night_qty),
        )
        db_conn.commit()
        return cat_id

    def test_normal_delta_high_confidence(self, db_conn: sqlite3.Connection) -> None:
        self._setup_morning_night(db_conn, morning_qty=20, night_qty=5)
        repo = SalesRepository(db_conn)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        count = repo.calculate_and_store_daily_sales(today, "122001")
        assert count == 1

        sales = repo.get_top_sellers(limit=10, date=today)
        assert len(sales) == 1
        assert sales[0].estimated_sales == 15
        assert sales[0].confidence == Confidence.HIGH
        assert sales[0].restock_flag is False

    def test_zero_sales_medium_confidence(self, db_conn: sqlite3.Connection) -> None:
        self._setup_morning_night(db_conn, morning_qty=10, night_qty=10)
        repo = SalesRepository(db_conn)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        count = repo.calculate_and_store_daily_sales(today, "122001")
        assert count == 1

        rows = db_conn.execute("SELECT * FROM daily_sales").fetchall()
        assert rows[0][6] == 0  # estimated_sales
        assert rows[0][7] == "medium"  # confidence

    def test_restock_low_confidence(self, db_conn: sqlite3.Connection) -> None:
        self._setup_morning_night(db_conn, morning_qty=5, night_qty=15)
        repo = SalesRepository(db_conn)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        count = repo.calculate_and_store_daily_sales(today, "122001")
        assert count == 1

        rows = db_conn.execute("SELECT * FROM daily_sales").fetchall()
        assert rows[0][6] == 0  # estimated_sales
        assert rows[0][7] == "low"  # confidence
        assert rows[0][8] == 1  # restock_flag


class TestScrapeRunRepository:
    def test_run_lifecycle(self, db_conn: sqlite3.Connection) -> None:
        repo = ScrapeRunRepository(db_conn)
        run = ScrapeRun(
            id="run-001",
            platform=Platform.BLINKIT,
            pincode="122001",
            category="Dairy & Bread",
            time_of_day=TimeOfDay.MORNING,
            started_at=datetime.utcnow(),
        )
        rid = repo.create_run(run)
        assert rid == "run-001"

        repo.complete_run("run-001", products_found=25, errors=2)

        today = datetime.utcnow().strftime("%Y-%m-%d")
        runs = repo.get_runs_by_date(today)
        assert len(runs) == 1
        assert runs[0].status == ScrapeRunStatus.COMPLETED
        assert runs[0].products_found == 25
        assert runs[0].errors == 2

    def test_fail_run(self, db_conn: sqlite3.Connection) -> None:
        repo = ScrapeRunRepository(db_conn)
        run = ScrapeRun(
            id="run-002",
            platform=Platform.ZEPTO,
            pincode="122002",
            category="Dairy & Bread",
            time_of_day=TimeOfDay.NIGHT,
            started_at=datetime.utcnow(),
        )
        repo.create_run(run)
        repo.fail_run("run-002", errors=5)

        today = datetime.utcnow().strftime("%Y-%m-%d")
        runs = repo.get_runs_by_date(today)
        failed = [r for r in runs if r.id == "run-002"]
        assert len(failed) == 1
        assert failed[0].status == ScrapeRunStatus.FAILED
        assert failed[0].errors == 5


class TestCanonicalRepository:
    def test_insert_and_map(self, db_conn: sqlite3.Connection) -> None:
        cat_repo = CatalogRepository(db_conn)
        pid1 = cat_repo.upsert_product(CatalogProduct(
            platform=Platform.BLINKIT, platform_product_id="1",
            name="Amul Taaza 500ml", brand="Amul", category="Dairy",
        ))
        pid2 = cat_repo.upsert_product(CatalogProduct(
            platform=Platform.ZEPTO, platform_product_id="2",
            name="Amul Taaza Toned Milk 500ml", brand="Amul", category="Dairy",
        ))

        canon_repo = CanonicalRepository(db_conn)
        cid = canon_repo.insert_canonical(CanonicalProduct(
            canonical_name="Amul Taaza Toned Fresh Milk 500ml",
            brand="Amul",
            category="Dairy",
            unit_normalized="500ml",
        ))
        assert cid > 0

        canon_repo.insert_mapping(ProductMapping(catalog_id=pid1, canonical_id=cid, similarity_score=0.95))
        canon_repo.insert_mapping(ProductMapping(catalog_id=pid2, canonical_id=cid, similarity_score=0.92))

        view = canon_repo.get_cross_platform_view()
        assert len(view) == 1
        assert len(view[0]["platforms"]) == 2

    def test_unmapped(self, db_conn: sqlite3.Connection) -> None:
        cat_repo = CatalogRepository(db_conn)
        cat_repo.upsert_product(CatalogProduct(
            platform=Platform.BLINKIT, platform_product_id="1",
            name="Unmapped Product", category="Dairy",
        ))
        canon_repo = CanonicalRepository(db_conn)
        unmapped = canon_repo.get_unmapped()
        assert len(unmapped) == 1
        assert unmapped[0].name == "Unmapped Product"
