"""Product matching via pre-computed Kaggle embeddings + reranker scores."""

import json
import logging
from pathlib import Path

from src.config.settings import settings
from src.embeddings.unit_normalizer import normalize_unit

logger = logging.getLogger(__name__)


class ProductEmbedder:
    """Loads pre-computed match results from Kaggle embedding pipeline."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self.cache_dir = cache_dir or settings.embedding_cache_dir

    def load_match_results(self, path: str | Path) -> dict:
        """Load match results JSON from Kaggle output."""
        data = json.loads(Path(path).read_text())
        logger.info(
            "Loaded %d matches from %s (model=%s, reranker=%s)",
            len(data.get("matches", [])),
            path,
            data.get("model", "unknown"),
            data.get("reranker", "unknown"),
        )
        return data

    def find_matches_from_results(
        self,
        match_results: dict,
        threshold: float | None = None,
    ) -> list[tuple[int, int, float]]:
        """Extract matches above threshold from pre-computed results.

        Returns (query_id, corpus_id, rerank_score) tuples.
        query_id = non-anchor product catalog ID
        corpus_id = anchor product catalog ID
        """
        threshold = threshold or settings.embedding_similarity_threshold
        matches = []
        for m in match_results.get("matches", []):
            score = m.get("rerank_score", m.get("score", 0.0))
            if score >= threshold:
                matches.append((m["query_id"], m["corpus_id"], score))
        return matches

    @staticmethod
    def compose_product_text(name: str, brand: str | None = None, unit: str | None = None) -> str:
        """Compose a text representation for embedding."""
        parts = []
        if brand:
            parts.append(brand)
        parts.append(name)
        if unit:
            norm = normalize_unit(unit)
            parts.append(norm if norm else unit)
        return " ".join(parts)
