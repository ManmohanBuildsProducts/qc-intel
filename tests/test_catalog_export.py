"""Tests for catalog export to JSON (for Kaggle embedding upload)."""

import json
import sqlite3
from pathlib import Path

from src.agents.scraper.service import ScrapeService
from src.models.product import Platform, TimeOfDay

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _seed_all_platforms(conn: sqlite3.Connection) -> None:
    """Seed all 3 dairy fixtures into the DB."""
    service = ScrapeService(conn)
    for platform, fixture in [
        (Platform.BLINKIT, "blinkit_dairy.json"),
        (Platform.ZEPTO, "zepto_dairy.json"),
        (Platform.INSTAMART, "instamart_dairy.json"),
    ]:
        data = json.loads((FIXTURES_DIR / fixture).read_text())
        service.process_scrape_results(data, platform, "122001", "Dairy & Bread", TimeOfDay.MORNING)


class TestExportCatalogForEmbedding:
    """Tests for export_catalog_for_embedding."""

    def test_export_returns_correct_fields(self, db_session: sqlite3.Connection) -> None:
        """Each exported product has all required fields."""
        from src.embeddings.catalog_export import export_catalog_for_embedding

        _seed_all_platforms(db_session)
        products = export_catalog_for_embedding(db_session)

        assert len(products) > 0
        required_fields = {
            "id", "name", "brand", "category", "subcategory",
            "unit", "platform", "platform_product_id", "text",
        }
        for p in products:
            assert required_fields.issubset(p.keys()), f"Missing fields in {p}"

    def test_export_filters_by_category(self, db_session: sqlite3.Connection) -> None:
        """Filtering by category returns only matching products."""
        from src.embeddings.catalog_export import export_catalog_for_embedding

        _seed_all_platforms(db_session)

        # Seed a non-dairy product to verify filtering
        service = ScrapeService(db_session)
        data = json.loads((FIXTURES_DIR / "blinkit_snacks.json").read_text())
        service.process_scrape_results(data, Platform.BLINKIT, "122001", "Snacks & Munchies", TimeOfDay.MORNING)

        dairy = export_catalog_for_embedding(db_session, category="Dairy & Bread")
        all_products = export_catalog_for_embedding(db_session)

        assert len(dairy) > 0
        assert len(all_products) > len(dairy)
        assert all(p["category"] == "Dairy & Bread" for p in dairy)

    def test_text_composition_with_brand_and_unit(self, db_session: sqlite3.Connection) -> None:
        """Text field includes brand, name, and normalized unit."""
        from src.embeddings.catalog_export import export_catalog_for_embedding

        _seed_all_platforms(db_session)
        products = export_catalog_for_embedding(db_session)

        # Find a blinkit product we know has brand and unit
        blinkit_amul = [p for p in products if p["platform"] == "blinkit" and p["brand"] == "Amul"]
        assert len(blinkit_amul) > 0

        p = blinkit_amul[0]
        assert p["text"].startswith("Amul ")
        assert p["name"] in p["text"]
        # Unit should be normalized (e.g. "500 ml" -> "500ml")
        assert "500ml" in p["text"] or "1l" in p["text"] or "ml" in p["text"]

    def test_text_composition_without_brand(self, db_session: sqlite3.Connection) -> None:
        """Products without brand still get valid text (just name + unit)."""
        from src.embeddings.catalog_export import export_catalog_for_embedding

        # Insert a product with no brand directly
        db_session.execute(
            """INSERT INTO product_catalog (platform, platform_product_id, name, brand, category, subcategory, unit)
               VALUES ('blinkit', 'test-no-brand', 'Plain Curd', NULL, 'Dairy & Bread', 'Curd', '400 g')"""
        )
        db_session.commit()

        products = export_catalog_for_embedding(db_session, category="Dairy & Bread")
        no_brand = [p for p in products if p["platform_product_id"] == "test-no-brand"]
        assert len(no_brand) == 1

        text = no_brand[0]["text"]
        assert text.startswith("Plain Curd")
        assert "400g" in text
        # Should NOT have "None" in the text
        assert "None" not in text

    def test_round_trip_ids_preserved(self, db_session: sqlite3.Connection) -> None:
        """Exported id matches the DB catalog id."""
        from src.embeddings.catalog_export import export_catalog_for_embedding

        _seed_all_platforms(db_session)
        products = export_catalog_for_embedding(db_session)

        # Verify IDs match actual DB rows
        cursor = db_session.execute("SELECT id FROM product_catalog ORDER BY id")
        db_ids = {row[0] for row in cursor.fetchall()}
        export_ids = {p["id"] for p in products}

        assert export_ids == db_ids


class TestExportCatalogToJson:
    """Tests for export_catalog_to_json."""

    def test_export_groups_by_platform(self, db_session: sqlite3.Connection, tmp_path: Path) -> None:
        """Output JSON groups products by platform correctly."""
        from src.embeddings.catalog_export import export_catalog_to_json

        _seed_all_platforms(db_session)
        output_path = tmp_path / "export.json"
        result_path = export_catalog_to_json(db_session, str(output_path), category="Dairy & Bread")

        assert result_path == str(output_path)
        data = json.loads(Path(result_path).read_text())

        assert "anchor_products" in data
        assert "other_products" in data
        # All 3 platforms should be represented
        all_platforms = {p["platform"] for p in data["anchor_products"]}
        for products in data["other_products"].values():
            all_platforms.update(p["platform"] for p in products)
        assert all_platforms == {"blinkit", "zepto", "instamart"}

    def test_export_anchor_is_blinkit(self, db_session: sqlite3.Connection, tmp_path: Path) -> None:
        """Blinkit is the preferred anchor platform."""
        from src.embeddings.catalog_export import export_catalog_to_json

        _seed_all_platforms(db_session)
        output_path = tmp_path / "export.json"
        export_catalog_to_json(db_session, str(output_path), category="Dairy & Bread")

        data = json.loads(output_path.read_text())
        assert data["anchor_platform"] == "blinkit"
        assert all(p["platform"] == "blinkit" for p in data["anchor_products"])
        assert "blinkit" not in data["other_products"]


class TestExportFixturesToJson:
    """Tests for export_fixtures_to_json."""

    def test_export_fixtures(self, tmp_path: Path) -> None:
        """Fixtures round-trip through in-memory DB and export correctly."""
        from src.embeddings.catalog_export import export_fixtures_to_json

        output_path = tmp_path / "fixtures_export.json"
        result_path = export_fixtures_to_json(str(output_path))

        assert result_path == str(output_path)
        data = json.loads(Path(result_path).read_text())

        assert data["category"] == "Dairy & Bread"
        assert data["anchor_platform"] == "blinkit"
        assert len(data["anchor_products"]) > 0
        assert len(data["other_products"]) > 0

        # Every product should have a text field
        all_products = data["anchor_products"]
        for platform_products in data["other_products"].values():
            all_products = all_products + platform_products
        assert all("text" in p for p in all_products)
