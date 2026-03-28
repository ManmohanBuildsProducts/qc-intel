"""Kaggle embedding client — push notebooks, poll status, download results."""

import json
import logging
import re
import shutil
import time
from pathlib import Path

from kaggle.api.kaggle_api_extended import KaggleApi

from src.config.settings import settings

logger = logging.getLogger(__name__)

KAGGLE_DIR = Path(__file__).parent.parent.parent / "kaggle"


class KaggleEmbeddingClient:
    """Client to trigger Kaggle embedding notebooks and retrieve results."""

    def __init__(
        self,
        username: str | None = None,
        kernel_slug: str | None = None,
        cache_dir: str | None = None,
    ) -> None:
        self.username = username or settings.kaggle_username
        self.kernel_slug = kernel_slug or settings.kaggle_kernel_slug
        self.cache_dir = cache_dir or settings.embedding_cache_dir
        self._api: KaggleApi | None = None

        Path(self.cache_dir).mkdir(parents=True, exist_ok=True)

    @property
    def api(self) -> KaggleApi:
        if self._api is None:
            self._api = KaggleApi()
            self._api.authenticate()
        return self._api

    @property
    def kernel_id(self) -> str:
        return f"{self.username}/{self.kernel_slug}"

    def cache_path_for_category(self, category: str) -> Path:
        """Get cache file path for a category's match results."""
        slug = re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")
        return Path(self.cache_dir) / f"match_results_{slug}.json"

    def upload_catalog(self, catalog_path: str, category: str) -> None:
        """Upload catalog JSON as a Kaggle dataset for the kernel to consume."""
        dataset_slug = f"{self.username}/qc-intel-catalog"
        staging = Path(self.cache_dir) / "staging"
        staging.mkdir(parents=True, exist_ok=True)

        # Copy catalog to staging as catalog.json
        shutil.copy2(catalog_path, staging / "catalog.json")

        # Write dataset metadata
        metadata = {
            "id": dataset_slug,
            "title": "QC Intel Product Catalog",
            "licenses": [{"name": "CC0-1.0"}],
        }
        (staging / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2))

        try:
            self.api.dataset_create_version(
                str(staging),
                version_notes=f"Category: {category}",
                dir_mode="zip",
            )
            logger.info("Dataset updated: %s (category: %s)", dataset_slug, category)
        except Exception:
            # First upload — create instead of update
            self.api.dataset_create_new(str(staging), dir_mode="zip")
            logger.info("Dataset created: %s (category: %s)", dataset_slug, category)

    def push_kernel(self) -> None:
        """Push the embedding kernel to Kaggle for execution."""
        self.api.kernels_push(str(KAGGLE_DIR))
        logger.info("Kernel pushed: %s", self.kernel_id)

    def poll_status(self, timeout: int = 900, interval: int = 30) -> str:
        """Poll kernel status until complete or error. Returns final status."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = self.api.kernels_status(self.kernel_id)
            status = response.get("status", response) if isinstance(response, dict) else str(response)
            logger.info("Kernel status: %s", status)

            if status in ("complete", "error", "cancelAcknowledged"):
                return status

            time.sleep(interval)

        logger.error("Kernel timed out after %ds", timeout)
        return "timeout"

    def download_results(self, category: str) -> Path | None:
        """Download kernel output and cache match results."""
        output_dir = Path(self.cache_dir) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        self.api.kernels_output(self.kernel_id, str(output_dir))

        match_file = output_dir / "match_results.json"
        if not match_file.exists():
            logger.error("match_results.json not found in kernel output")
            return None

        # Copy to category-specific cache path
        cache_path = self.cache_path_for_category(category)
        shutil.copy2(match_file, cache_path)
        logger.info("Match results cached: %s", cache_path)

        # Also cache benchmark results if present
        benchmark_file = output_dir / "benchmark_results.json"
        if benchmark_file.exists():
            dest = Path(self.cache_dir) / "benchmark_results.json"
            shutil.copy2(benchmark_file, dest)
            logger.info("Benchmark results cached: %s", dest)

        return cache_path

    def load_match_results(self, category: str) -> dict | None:
        """Load cached match results for a category. Returns None if not cached."""
        cache_path = self.cache_path_for_category(category)
        if not cache_path.exists():
            return None
        return json.loads(cache_path.read_text())

    def run_embedding_pipeline(self, catalog_path: str, category: str) -> dict | None:
        """Full pipeline: upload catalog → push kernel → poll → download → return results."""
        logger.info("Starting Kaggle embedding pipeline for: %s", category)

        self.upload_catalog(catalog_path, category)
        self.push_kernel()

        status = self.poll_status()
        if status != "complete":
            logger.error("Kernel did not complete successfully: %s", status)
            return None

        result_path = self.download_results(category)
        if result_path is None:
            return None

        return self.load_match_results(category)
