"""Product name embeddings using sentence-transformers."""

import logging

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

from src.config.settings import settings

logger = logging.getLogger(__name__)


class ProductEmbedder:
    """Wrapper around sentence-transformers for product similarity."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.embedding_model
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        """Generate embeddings for a list of texts."""
        return self.model.encode(texts, convert_to_numpy=True)

    def similarity_matrix(self, texts_a: list[str], texts_b: list[str]) -> np.ndarray:
        """Compute cosine similarity matrix between two sets of texts."""
        emb_a = self.embed(texts_a)
        emb_b = self.embed(texts_b)
        return cosine_similarity(emb_a, emb_b)

    def find_matches(
        self,
        query_texts: list[str],
        corpus_texts: list[str],
        threshold: float | None = None,
    ) -> list[tuple[int, int, float]]:
        """Find matches above threshold. Returns (query_idx, corpus_idx, similarity)."""
        threshold = threshold or settings.embedding_similarity_threshold
        sim_matrix = self.similarity_matrix(query_texts, corpus_texts)
        matches = []
        for i in range(len(query_texts)):
            for j in range(len(corpus_texts)):
                if sim_matrix[i][j] >= threshold:
                    matches.append((i, j, float(sim_matrix[i][j])))
        return matches

    @staticmethod
    def compose_product_text(name: str, brand: str | None = None, unit: str | None = None) -> str:
        """Compose a text representation for embedding."""
        parts = []
        if brand:
            parts.append(brand)
        parts.append(name)
        if unit:
            parts.append(unit)
        return " ".join(parts)
