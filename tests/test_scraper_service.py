"""Integration tests for ScrapeService with real DB."""

import sqlite3

from src.agents.scraper.service import ScrapeService
from src.models.product import Platform, ScrapeRunStatus, TimeOfDay


class TestScrapeServiceBlinkit:
    def test_process_blinkit_scrape(
        self, db_session: sqlite3.Connection, blinkit_fixture_data: list[dict]
    ) -> None:
        service = ScrapeService(db_session)
        run = service.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        assert run.status == ScrapeRunStatus.COMPLETED
        assert run.products_found == 10
        assert run.errors == 0
        assert run.platform == Platform.BLINKIT

        # Verify catalog entries
        catalog_count = db_session.execute("SELECT COUNT(*) FROM product_catalog").fetchone()[0]
        assert catalog_count == 10

        # Verify observations
        obs_count = db_session.execute("SELECT COUNT(*) FROM product_observations").fetchone()[0]
        assert obs_count == 10

        # Verify scrape run persisted
        run_row = db_session.execute("SELECT * FROM scrape_runs WHERE id = ?", (run.id,)).fetchone()
        assert run_row is not None
        assert run_row[9] == "completed"  # status column


class TestScrapeServiceZepto:
    def test_process_zepto_scrape(
        self, db_session: sqlite3.Connection, zepto_fixture_data: list[dict]
    ) -> None:
        service = ScrapeService(db_session)
        run = service.process_scrape_results(
            zepto_fixture_data, Platform.ZEPTO, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        assert run.status == ScrapeRunStatus.COMPLETED
        assert run.products_found == 10
        assert run.errors == 0


class TestScrapeServiceInstamart:
    def test_process_instamart_scrape(
        self, db_session: sqlite3.Connection, instamart_fixture_data: list[dict]
    ) -> None:
        service = ScrapeService(db_session)
        run = service.process_scrape_results(
            instamart_fixture_data, Platform.INSTAMART, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        assert run.status == ScrapeRunStatus.COMPLETED
        assert run.products_found == 10
        assert run.errors == 0

        # Verify OOS product still in catalog
        oos = db_session.execute(
            "SELECT po.in_stock FROM product_observations po "
            "JOIN product_catalog pc ON po.catalog_id = pc.id "
            "WHERE pc.name = 'Modern Multigrain Bread'"
        ).fetchone()
        assert oos is not None
        assert oos[0] == 0  # in_stock = False stored as 0


class TestUpsertExistingProduct:
    def test_upsert_existing_product(
        self, db_session: sqlite3.Connection, blinkit_fixture_data: list[dict]
    ) -> None:
        service = ScrapeService(db_session)

        # First scrape — morning
        service.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        # Second scrape — night (same products)
        service.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.NIGHT
        )

        # Catalog count should stay 10 (upserted, not duplicated)
        catalog_count = db_session.execute("SELECT COUNT(*) FROM product_catalog").fetchone()[0]
        assert catalog_count == 10

        # Observation count should be 20 (10 morning + 10 night)
        obs_count = db_session.execute("SELECT COUNT(*) FROM product_observations").fetchone()[0]
        assert obs_count == 20


class TestScrapeRunLifecycle:
    def test_scrape_run_lifecycle(
        self, db_session: sqlite3.Connection, blinkit_fixture_data: list[dict]
    ) -> None:
        service = ScrapeService(db_session)
        run = service.process_scrape_results(
            blinkit_fixture_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        # Check the persisted run
        row = db_session.execute("SELECT * FROM scrape_runs WHERE id = ?", (run.id,)).fetchone()
        assert row[9] == "completed"
        assert row[7] == 10  # products_found
        assert row[8] == 0  # errors
        assert row[6] is not None  # completed_at


class TestPartialFailure:
    def test_partial_failure(self, db_session: sqlite3.Connection) -> None:
        # Mix valid and invalid items (price=0 gets skipped by parser, not service error)
        items = [
            {"id": 1, "name": "Good Product", "price": 25.0, "mrp": 30.0, "available": True, "max_allowed_quantity": 3},
            {"id": 2, "name": "Zero Price", "price": 0, "available": True, "max_allowed_quantity": 0},
            {"id": 3, "name": "Another Good", "price": 15.0, "mrp": 15.0, "available": True, "max_allowed_quantity": 2},
        ]

        service = ScrapeService(db_session)
        run = service.process_scrape_results(
            items, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING
        )

        # Parser skips zero-price → 2 products make it through
        assert run.products_found == 2
        assert run.errors == 0

        catalog_count = db_session.execute("SELECT COUNT(*) FROM product_catalog").fetchone()[0]
        assert catalog_count == 2
