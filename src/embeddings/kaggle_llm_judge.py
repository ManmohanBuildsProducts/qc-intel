"""Kaggle LLM judge client — push ambiguous pairs, trigger kernel, download verdicts."""

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from kaggle.api.kaggle_api_extended import KaggleApi

from src.config.settings import settings

logger = logging.getLogger(__name__)

JUDGE_KERNEL_DIR = Path(__file__).parent.parent.parent / "kaggle" / "llm-judge"


class KaggleLLMJudgeClient:
    """Client to run open-source LLM match validation on Kaggle GPU."""

    def __init__(
        self,
        username: str | None = None,
        kernel_slug: str = "qc-intel-llm-judge",
        cache_dir: str | None = None,
    ) -> None:
        self.username = username or settings.kaggle_username
        self.kernel_slug = kernel_slug
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

    @property
    def _results_cache_path(self) -> Path:
        return Path(self.cache_dir) / "judge_results.json"

    @property
    def _benchmark_cache_path(self) -> Path:
        return Path(self.cache_dir) / "judge_benchmark.json"

    def upload_pairs(
        self,
        pairs: list[dict[str, Any]],
        gemini_ground_truth: dict[int, bool] | None = None,
    ) -> None:
        """Upload ambiguous pairs as a Kaggle dataset for the judge kernel.

        Args:
            pairs: List of dicts with keys: pair_id, catalog_id_a, catalog_id_b,
                   name_a, brand_a, unit_a, name_b, brand_b, unit_b, similarity.
            gemini_ground_truth: Optional mapping of pair_id -> Gemini YES/NO verdict.
                                If provided, enables benchmark mode in the kernel.
        """
        dataset_slug = f"{self.username}/qc-intel-judge-pairs"
        staging = Path(self.cache_dir) / "judge_staging"
        staging.mkdir(parents=True, exist_ok=True)

        # Attach Gemini ground truth if available (for benchmarking)
        if gemini_ground_truth:
            for pair in pairs:
                pid = pair.get("pair_id")
                if pid in gemini_ground_truth:
                    pair["gemini_verdict"] = "YES" if gemini_ground_truth[pid] else "NO"

        data = {"pairs": pairs, "count": len(pairs)}
        (staging / "pairs.json").write_text(json.dumps(data, indent=2))

        metadata = {
            "id": dataset_slug,
            "title": "QC Intel Judge Pairs",
            "licenses": [{"name": "CC0-1.0"}],
        }
        (staging / "dataset-metadata.json").write_text(json.dumps(metadata, indent=2))

        try:
            self.api.dataset_create_version(
                str(staging),
                version_notes=f"{len(pairs)} pairs",
                dir_mode="zip",
            )
            logger.info("Judge dataset updated: %s (%d pairs)", dataset_slug, len(pairs))
        except Exception:
            self.api.dataset_create_new(str(staging), dir_mode="zip")
            logger.info("Judge dataset created: %s (%d pairs)", dataset_slug, len(pairs))

    def push_kernel(self) -> None:
        """Push the LLM judge kernel to Kaggle for execution."""
        self.api.kernels_push(str(JUDGE_KERNEL_DIR))
        logger.info("Judge kernel pushed: %s", self.kernel_id)

    def poll_status(self, timeout: int = 1200, interval: int = 30) -> str:
        """Poll kernel status until complete or error. Returns final status.

        Timeout is higher than embedding kernel (1200s vs 900s) because
        LLM inference is slower.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            response = self.api.kernels_status(self.kernel_id)
            status = response.get("status", response) if isinstance(response, dict) else str(response)
            logger.info("Judge kernel status: %s", status)

            if status in ("complete", "error", "cancelAcknowledged"):
                return status

            time.sleep(interval)

        logger.error("Judge kernel timed out after %ds", timeout)
        return "timeout"

    def download_results(self) -> dict[str, Any] | None:
        """Download kernel output and cache judge results."""
        output_dir = Path(self.cache_dir) / "judge_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        self.api.kernels_output(self.kernel_id, str(output_dir))

        results_file = output_dir / "judge_results.json"
        if not results_file.exists():
            logger.error("judge_results.json not found in kernel output")
            return None

        # Cache results
        shutil.copy2(results_file, self._results_cache_path)
        logger.info("Judge results cached: %s", self._results_cache_path)

        # Cache benchmark if present
        benchmark_file = output_dir / "benchmark_results.json"
        if benchmark_file.exists():
            shutil.copy2(benchmark_file, self._benchmark_cache_path)
            logger.info("Judge benchmark cached: %s", self._benchmark_cache_path)

        return json.loads(self._results_cache_path.read_text())

    def load_results(self) -> dict[str, Any] | None:
        """Load cached judge results. Returns None if not cached."""
        if not self._results_cache_path.exists():
            return None
        return json.loads(self._results_cache_path.read_text())

    def load_benchmark(self) -> dict[str, Any] | None:
        """Load cached benchmark results. Returns None if not cached."""
        if not self._benchmark_cache_path.exists():
            return None
        return json.loads(self._benchmark_cache_path.read_text())

    def get_verdicts(self) -> dict[int, bool]:
        """Load cached results and return mapping of pair_id -> is_match (bool).

        This is the primary interface for the normalizer/eval to consume verdicts.
        """
        results = self.load_results()
        if not results:
            return {}

        verdicts: dict[int, bool] = {}
        for v in results.get("verdicts", []):
            pair_id = v.get("pair_id")
            if pair_id is not None:
                verdicts[pair_id] = v["verdict"] == "YES"
        return verdicts

    def run_judge_pipeline(
        self,
        pairs: list[dict[str, Any]],
        gemini_ground_truth: dict[int, bool] | None = None,
    ) -> dict[str, Any] | None:
        """Full pipeline: upload pairs -> push kernel -> poll -> download -> return results."""
        logger.info("Starting Kaggle LLM judge pipeline (%d pairs)", len(pairs))

        self.upload_pairs(pairs, gemini_ground_truth)
        self.push_kernel()

        status = self.poll_status()
        if status != "complete":
            logger.error("Judge kernel did not complete: %s", status)
            return None

        return self.download_results()
