"""Tests for normalizer — embedder + normalization service."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.normalizer import NormalizerService
from src.agents.scraper.service import ScrapeService
from src.embeddings.product_embedder import ProductEmbedder
from src.models.product import CatalogProduct, Platform, TimeOfDay

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestProductEmbedder:
    def test_compose_product_text(self) -> None:
        text = ProductEmbedder.compose_product_text("Taaza Milk", "Amul", "500ml")
        assert text == "Amul Taaza Milk 500ml"

    def test_compose_product_text_no_brand(self) -> None:
        text = ProductEmbedder.compose_product_text("Taaza Milk", unit="500ml")
        assert text == "Taaza Milk 500ml"

    def test_compose_product_text_no_unit(self) -> None:
        text = ProductEmbedder.compose_product_text("Taaza Milk", "Amul")
        assert text == "Amul Taaza Milk"

    def test_compose_product_text_normalizes_unit(self) -> None:
        text = ProductEmbedder.compose_product_text("Taaza Milk", "Amul", "500 ml")
        assert text == "Amul Taaza Milk 500ml"

    def test_load_match_results(self, tmp_path: Path) -> None:
        data = {
            "model": "BAAI/bge-m3",
            "reranker": "BAAI/bge-reranker-v2-m3",
            "matches": [
                {"query_id": 1, "corpus_id": 2, "rerank_score": 0.95},
            ],
        }
        path = tmp_path / "match_results.json"
        path.write_text(json.dumps(data))

        embedder = ProductEmbedder(cache_dir=str(tmp_path))
        result = embedder.load_match_results(path)
        assert len(result["matches"]) == 1

    def test_find_matches_from_results(self) -> None:
        results = {
            "matches": [
                {"query_id": 1, "corpus_id": 10, "rerank_score": 0.95},
                {"query_id": 2, "corpus_id": 10, "rerank_score": 0.70},  # Below threshold
                {"query_id": 3, "corpus_id": 11, "rerank_score": 0.85},
            ],
        }
        embedder = ProductEmbedder()
        matches = embedder.find_matches_from_results(results, threshold=0.80)
        assert len(matches) == 2
        assert (1, 10, 0.95) in matches
        assert (3, 11, 0.85) in matches

    def test_find_matches_uses_score_fallback(self) -> None:
        """Benchmark results use 'score' instead of 'rerank_score'."""
        results = {
            "matches": [
                {"query_id": 1, "corpus_id": 10, "score": 0.90},
            ],
        }
        embedder = ProductEmbedder()
        matches = embedder.find_matches_from_results(results, threshold=0.80)
        assert len(matches) == 1


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

    def _build_match_results(self, db_session: sqlite3.Connection) -> dict:
        """Build mock match results from fixture data using IDs from DB."""
        # Get product IDs by platform
        rows = db_session.execute(
            "SELECT id, platform, name FROM product_catalog ORDER BY id"
        ).fetchall()
        blinkit = [r for r in rows if r[1] == "blinkit"]
        zepto = [r for r in rows if r[1] == "zepto"]
        instamart = [r for r in rows if r[1] == "instamart"]

        # Create matches: each zepto/instamart product maps to same-index blinkit product
        matches = []
        for i, zp in enumerate(zepto):
            if i < len(blinkit):
                matches.append({
                    "query_id": zp[0],
                    "corpus_id": blinkit[i][0],
                    "rerank_score": 0.95,
                    "query_text": zp[2],
                    "corpus_text": blinkit[i][2],
                })
        for i, im in enumerate(instamart):
            if i < len(blinkit):
                matches.append({
                    "query_id": im[0],
                    "corpus_id": blinkit[i][0],
                    "rerank_score": 0.90,
                    "query_text": im[2],
                    "corpus_text": blinkit[i][2],
                })

        return {
            "model": "BAAI/bge-m3",
            "reranker": "BAAI/bge-reranker-v2-m3",
            "category": "Dairy & Bread",
            "anchor_platform": "blinkit",
            "matches": matches,
        }

    def test_normalize_category_with_match_results(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
        zepto_fixture_data: list[dict],
        instamart_fixture_data: list[dict],
    ) -> None:
        self._seed_all_platforms(db_session, blinkit_fixture_data, zepto_fixture_data, instamart_fixture_data)
        match_results = self._build_match_results(db_session)

        normalizer = NormalizerService(db_session)
        result = normalizer.normalize_category("Dairy & Bread", match_results=match_results)

        assert result.canonical_products_created > 0
        assert result.mappings_created > 0
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
        match_results = self._build_match_results(db_session)

        normalizer = NormalizerService(db_session)
        normalizer.normalize_category("Dairy & Bread", match_results=match_results)

        count = db_session.execute("SELECT COUNT(*) FROM canonical_products").fetchone()[0]
        assert count > 0

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
        match_results = self._build_match_results(db_session)

        normalizer = NormalizerService(db_session)
        normalizer.normalize_category("Dairy & Bread", match_results=match_results)

        from src.db.repository import CanonicalRepository

        view = CanonicalRepository(db_session).get_cross_platform_view()
        assert len(view) > 0
        multi_platform = [v for v in view if len(v["platforms"]) > 1]
        assert len(multi_platform) > 0

    def test_normalize_without_match_results_creates_all_canonicals(
        self,
        db_session: sqlite3.Connection,
        blinkit_fixture_data: list[dict],
        zepto_fixture_data: list[dict],
        instamart_fixture_data: list[dict],
    ) -> None:
        """Without match results, every product becomes its own canonical."""
        self._seed_all_platforms(db_session, blinkit_fixture_data, zepto_fixture_data, instamart_fixture_data)

        # Mock kaggle_client to return None
        normalizer = NormalizerService(db_session)
        normalizer.kaggle_client = MagicMock()
        normalizer.kaggle_client.load_match_results.return_value = None

        result = normalizer.normalize_category("Dairy & Bread")

        # All 30 products should have mappings (each as its own canonical)
        total_products = db_session.execute(
            "SELECT COUNT(*) FROM product_catalog WHERE category = 'Dairy & Bread'"
        ).fetchone()[0]
        assert result.mappings_created == total_products


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
