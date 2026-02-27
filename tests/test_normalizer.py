"""Tests for normalizer — embedder + normalization service."""

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.normalizer import NormalizerService
from src.agents.scraper.service import ScrapeService
from src.embeddings.product_embedder import ProductEmbedder
from src.models.product import CatalogProduct, Platform, TimeOfDay


class TestProductEmbedder:
    def test_embed_returns_array(self) -> None:
        embedder = ProductEmbedder()
        result = embedder.embed(["Amul Taaza Toned Milk 500ml"])
        assert result.shape[0] == 1
        assert result.shape[1] > 0

    def test_similar_products_high_similarity(self) -> None:
        embedder = ProductEmbedder()
        sim = embedder.similarity_matrix(
            ["Amul Taaza Toned Fresh Milk 500ml"],
            ["Amul Taaza Toned Milk 500 ml"],
        )
        assert sim[0][0] > 0.85

    def test_dissimilar_products_low_similarity(self) -> None:
        embedder = ProductEmbedder()
        sim = embedder.similarity_matrix(
            ["Amul Taaza Toned Fresh Milk 500ml"],
            ["Harvest Gold White Bread 1 pack"],
        )
        assert sim[0][0] < 0.5

    def test_find_matches(self) -> None:
        embedder = ProductEmbedder()
        matches = embedder.find_matches(
            ["Amul Taaza Toned Milk 500ml"],
            ["Amul Taaza Fresh Milk 500ml", "Britannia Bread 400g"],
            threshold=0.8,
        )
        assert len(matches) >= 1
        assert matches[0][0] == 0  # query_idx
        assert matches[0][1] == 0  # corpus_idx (milk match)

    def test_compose_product_text(self) -> None:
        text = ProductEmbedder.compose_product_text("Taaza Milk", "Amul", "500ml")
        assert text == "Amul Taaza Milk 500ml"

    def test_compose_product_text_no_brand(self) -> None:
        text = ProductEmbedder.compose_product_text("Taaza Milk", unit="500ml")
        assert text == "Taaza Milk 500ml"


class TestNormalizerService:
    def _seed_all_platforms(
        self,
        db_session: sqlite3.Connection,
        blinkit_data: list[dict],
        zepto_data: list[dict],
        instamart_data: list[dict],
    ) -> None:
        """Helper: seed all 3 platforms into DB via ScrapeService."""
        service = ScrapeService(db_session)
        service.process_scrape_results(blinkit_data, Platform.BLINKIT, "122001", "Dairy & Bread", TimeOfDay.MORNING)
        service.process_scrape_results(zepto_data, Platform.ZEPTO, "122001", "Dairy & Bread", TimeOfDay.MORNING)
        service.process_scrape_results(instamart_data, Platform.INSTAMART, "122001", "Dairy & Bread", TimeOfDay.MORNING)

    def test_normalize_category(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
        zepto_fixture_data: list[dict],
        instamart_fixture_data: list[dict],
    ) -> None:
        self._seed_all_platforms(db_session, blinkit_fixture_data, zepto_fixture_data, instamart_fixture_data)

        normalizer = NormalizerService(db_session)
        result = normalizer.normalize_category("Dairy & Bread")

        assert result.canonical_products_created > 0
        assert result.mappings_created > 0
        # Should have mappings for all 30 products (10 per platform)
        assert result.mappings_created >= 20  # At least anchor + some matches

    def test_normalize_empty_category(self, db_session: sqlite3.Connection) -> None:
        normalizer = NormalizerService(db_session)
        result = normalizer.normalize_category("Nonexistent Category")
        assert result.canonical_products_created == 0
        assert result.mappings_created == 0

    def test_normalization_creates_canonical_products(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
        zepto_fixture_data: list[dict],
        instamart_fixture_data: list[dict],
    ) -> None:
        self._seed_all_platforms(db_session, blinkit_fixture_data, zepto_fixture_data, instamart_fixture_data)

        normalizer = NormalizerService(db_session)
        normalizer.normalize_category("Dairy & Bread")

        # Verify canonical products exist
        count = db_session.execute("SELECT COUNT(*) FROM canonical_products").fetchone()[0]
        assert count > 0

        # Verify mappings exist
        mapping_count = db_session.execute("SELECT COUNT(*) FROM product_mappings").fetchone()[0]
        assert mapping_count > 0

    def test_cross_platform_view_after_normalization(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
        zepto_fixture_data: list[dict],
        instamart_fixture_data: list[dict],
    ) -> None:
        self._seed_all_platforms(db_session, blinkit_fixture_data, zepto_fixture_data, instamart_fixture_data)

        normalizer = NormalizerService(db_session)
        normalizer.normalize_category("Dairy & Bread")

        from src.db.repository import CanonicalRepository

        view = CanonicalRepository(db_session).get_cross_platform_view()
        assert len(view) > 0
        # At least some products should have multiple platform mappings
        multi_platform = [v for v in view if len(v["platforms"]) > 1]
        assert len(multi_platform) > 0


class TestLLMValidation:
    @pytest.mark.asyncio
    async def test_validate_match_yes(self, db_session: sqlite3.Connection) -> None:
        normalizer = NormalizerService(db_session)
        product_a = CatalogProduct(
            id=1,
            platform=Platform.BLINKIT,
            platform_product_id="1",
            name="Amul Taaza Milk",
            brand="Amul",
            category="Dairy",
            unit="500ml",
        )
        product_b = CatalogProduct(
            id=2,
            platform=Platform.ZEPTO,
            platform_product_id="2",
            name="Amul Taaza Toned Milk",
            brand="Amul",
            category="Dairy",
            unit="500 ml",
        )

        mock_response = MagicMock()
        mock_response.text = "YES"

        with patch("src.agents.normalizer.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            result = await normalizer._validate_match_with_llm(product_a, product_b, 0.78)

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_match_no(self, db_session: sqlite3.Connection) -> None:
        normalizer = NormalizerService(db_session)
        product_a = CatalogProduct(
            id=1,
            platform=Platform.BLINKIT,
            platform_product_id="1",
            name="Amul Butter",
            brand="Amul",
            category="Dairy",
            unit="100g",
        )
        product_b = CatalogProduct(
            id=2,
            platform=Platform.ZEPTO,
            platform_product_id="2",
            name="Amul Paneer",
            brand="Amul",
            category="Dairy",
            unit="200g",
        )

        mock_response = MagicMock()
        mock_response.text = "NO"

        with patch("src.agents.normalizer.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client
            result = await normalizer._validate_match_with_llm(product_a, product_b, 0.72)

        assert result is False
