"""Tests for Kaggle LLM judge client."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.embeddings.kaggle_llm_judge import KaggleLLMJudgeClient


@pytest.fixture
def judge_client(tmp_path: Path) -> KaggleLLMJudgeClient:
    with patch("src.embeddings.kaggle_llm_judge.settings") as mock_settings:
        mock_settings.kaggle_username = "testuser"
        mock_settings.embedding_cache_dir = str(tmp_path / "cache")
        client = KaggleLLMJudgeClient(
            username="testuser",
            cache_dir=str(tmp_path / "cache"),
        )
    return client


class TestKaggleLLMJudgeClient:
    def test_kernel_id(self, judge_client: KaggleLLMJudgeClient) -> None:
        assert judge_client.kernel_id == "testuser/qc-intel-llm-judge-qwen2-5-7b-instruct"

    def test_get_verdicts_empty(self, judge_client: KaggleLLMJudgeClient) -> None:
        verdicts = judge_client.get_verdicts()
        assert verdicts == {}

    def test_get_verdicts_from_cache(self, judge_client: KaggleLLMJudgeClient) -> None:
        # Write cached results
        results = {
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "count": 2,
            "verdicts": [
                {"pair_id": 1, "verdict": "YES"},
                {"pair_id": 2, "verdict": "NO"},
            ],
        }
        cache_path = judge_client._results_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(results))

        verdicts = judge_client.get_verdicts()
        assert verdicts == {1: True, 2: False}

    def test_load_results_none_when_no_cache(self, judge_client: KaggleLLMJudgeClient) -> None:
        assert judge_client.load_results() is None

    def test_load_benchmark_none_when_no_cache(self, judge_client: KaggleLLMJudgeClient) -> None:
        assert judge_client.load_benchmark() is None

    def test_load_benchmark_from_cache(self, judge_client: KaggleLLMJudgeClient) -> None:
        benchmark = {
            "accuracy": 0.96,
            "passed": True,
        }
        cache_path = judge_client._benchmark_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(benchmark))

        result = judge_client.load_benchmark()
        assert result["accuracy"] == 0.96
        assert result["passed"] is True

    def test_upload_pairs_with_ground_truth(self, judge_client: KaggleLLMJudgeClient) -> None:
        pairs = [
            {
                "pair_id": 1,
                "name_a": "Amul Taaza",
                "brand_a": "Amul",
                "unit_a": "500ml",
                "name_b": "Amul Taaza Milk",
                "brand_b": "Amul",
                "unit_b": "500 ml",
                "similarity": 0.83,
            }
        ]
        gt = {1: True}

        mock_api = MagicMock()
        judge_client._api = mock_api

        judge_client.upload_pairs(pairs, gemini_ground_truth=gt)

        # Verify ground truth was attached
        assert pairs[0]["gemini_verdict"] == "YES"

        # Verify API was called
        assert mock_api.dataset_create_version.called or mock_api.dataset_create_new.called
