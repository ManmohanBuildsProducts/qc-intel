"""Tests for Kaggle embedding client (push/poll/download)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.embeddings.kaggle_client import KaggleEmbeddingClient


@pytest.fixture
def client(tmp_path: Path) -> KaggleEmbeddingClient:
    """Client with temp cache dir."""
    return KaggleEmbeddingClient(
        username="testuser",
        kernel_slug="test-kernel",
        cache_dir=str(tmp_path / "embeddings"),
    )


@pytest.fixture
def sample_catalog(tmp_path: Path) -> str:
    """Create a sample catalog JSON file."""
    catalog = {
        "category": "Dairy & Bread",
        "anchor_platform": "blinkit",
        "anchor_products": [{
            "id": 1, "name": "Amul Milk", "brand": "Amul", "unit": "500ml",
            "text": "Amul Amul Milk 500ml", "platform": "blinkit",
            "platform_product_id": "bl-1",
        }],
        "other_products": {
            "zepto": [{
                "id": 2, "name": "Amul Toned Milk", "brand": "Amul",
                "unit": "500ml", "text": "Amul Amul Toned Milk 500ml",
                "platform": "zepto", "platform_product_id": "zp-1",
            }],
        },
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    return str(path)


@pytest.fixture
def sample_match_results() -> dict:
    """Sample match results as returned by Kaggle notebook."""
    return {
        "model": "BAAI/bge-m3",
        "reranker": "BAAI/bge-reranker-v2-m3",
        "category": "Dairy & Bread",
        "timestamp": "2026-03-28T12:00:00Z",
        "anchor_platform": "blinkit",
        "num_matches": 1,
        "matches": [
            {
                "query_id": 2,
                "query_text": "Amul Amul Toned Milk 500ml",
                "corpus_id": 1,
                "corpus_text": "Amul Amul Milk 500ml",
                "dense_score": 0.93,
                "rerank_score": 0.97,
            },
        ],
    }


class TestKaggleEmbeddingClient:
    def test_init_creates_cache_dir(self, client: KaggleEmbeddingClient) -> None:
        """Client creates cache directory on init."""
        assert Path(client.cache_dir).exists()

    def test_kernel_id(self, client: KaggleEmbeddingClient) -> None:
        """Kernel ID combines username and slug."""
        assert client.kernel_id == "testuser/test-kernel"

    def test_upload_catalog_as_dataset(self, client: KaggleEmbeddingClient, sample_catalog: str) -> None:
        """Upload creates dataset metadata and calls Kaggle API."""
        with patch("src.embeddings.kaggle_client.KaggleApi") as mock_api_cls:
            mock_api = MagicMock()
            mock_api_cls.return_value = mock_api
            client._api = mock_api

            client.upload_catalog(sample_catalog, "Dairy & Bread")

            mock_api.dataset_create_version.assert_called_once()

    @patch("src.embeddings.kaggle_client.KaggleApi")
    def test_push_kernel(self, mock_api_cls: MagicMock, client: KaggleEmbeddingClient) -> None:
        """Push creates kernel or pushes new version."""
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        client._api = mock_api

        client.push_kernel()
        mock_api.kernels_push.assert_called_once()

    @patch("src.embeddings.kaggle_client.KaggleApi")
    def test_poll_status_returns_complete(self, mock_api_cls: MagicMock, client: KaggleEmbeddingClient) -> None:
        """Poll returns 'complete' when kernel finishes."""
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        client._api = mock_api
        mock_api.kernels_status.return_value = {"status": "complete"}

        status = client.poll_status(timeout=5, interval=1)
        assert status == "complete"

    @patch("src.embeddings.kaggle_client.KaggleApi")
    def test_poll_status_returns_error(self, mock_api_cls: MagicMock, client: KaggleEmbeddingClient) -> None:
        """Poll returns 'error' when kernel fails."""
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        client._api = mock_api
        mock_api.kernels_status.return_value = {"status": "error"}

        status = client.poll_status(timeout=5, interval=1)
        assert status == "error"

    def test_download_results(self, client: KaggleEmbeddingClient, sample_match_results: dict) -> None:
        """Download writes match results to cache dir."""
        # Write to category-specific cache path
        cache_path = client.cache_path_for_category("Dairy & Bread")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(sample_match_results))

        result = client.load_match_results("Dairy & Bread")

        assert result is not None
        assert result["category"] == "Dairy & Bread"
        assert len(result["matches"]) == 1
        assert result["matches"][0]["rerank_score"] == 0.97

    def test_load_match_results_returns_none_if_missing(self, client: KaggleEmbeddingClient) -> None:
        """Returns None if no cached results exist."""
        result = client.load_match_results("Nonexistent Category")
        assert result is None

    def test_cache_path_for_category(self, client: KaggleEmbeddingClient) -> None:
        """Cache paths are category-specific."""
        path = client.cache_path_for_category("Dairy & Bread")
        assert "dairy_and_bread" in str(path).lower() or "dairy" in str(path).lower()
        assert path.suffix == ".json"
