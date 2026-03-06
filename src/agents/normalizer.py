"""Normalizer agent — cross-platform product matching via embeddings + Gemini validation."""

import logging
import sqlite3

from google import genai
from google.genai import types as genai_types

from src.config.settings import settings
from src.db.repository import CanonicalRepository
from src.embeddings.product_embedder import ProductEmbedder
from src.embeddings.unit_normalizer import normalize_unit
from src.models.product import (
    CanonicalProduct,
    CatalogProduct,
    NormalizationResult,
    Platform,
    ProductMapping,
)

logger = logging.getLogger(__name__)

# Thresholds
HIGH_CONFIDENCE_THRESHOLD = 0.85
AMBIGUOUS_LOWER_THRESHOLD = 0.70


class NormalizerService:
    """Cross-platform product normalization using embeddings and optional Claude validation."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.canonical_repo = CanonicalRepository(conn)
        self.embedder = ProductEmbedder()

    def normalize_category(self, category: str) -> NormalizationResult:
        """Match products across platforms for a category. Blinkit = anchor platform."""
        # Get unmapped products
        all_unmapped = self.canonical_repo.get_unmapped()
        category_products = [p for p in all_unmapped if p.category == category]

        if not category_products:
            return NormalizationResult(
                canonical_products_created=0,
                mappings_created=0,
                unmapped_count=0,
            )

        # Group by platform
        by_platform: dict[Platform, list[CatalogProduct]] = {}
        for p in category_products:
            by_platform.setdefault(p.platform, []).append(p)

        # Blinkit = anchor
        anchor_products = by_platform.pop(Platform.BLINKIT, [])

        if not anchor_products:
            # If no Blinkit products, use first available platform as anchor
            first_platform = next(iter(by_platform))
            anchor_products = by_platform.pop(first_platform)

        # Create canonical products for all anchor products
        canonical_created = 0
        mappings_created = 0
        anchor_canonical_ids: list[int] = []

        anchor_texts = [
            self.embedder.compose_product_text(p.name, p.brand, normalize_unit(p.unit))
            for p in anchor_products
        ]

        for anchor in anchor_products:
            canonical = CanonicalProduct(
                canonical_name=anchor.name,
                brand=anchor.brand,
                category=category,
                unit_normalized=normalize_unit(anchor.unit),
            )
            cid = self.canonical_repo.insert_canonical(canonical)
            anchor_canonical_ids.append(cid)
            self.canonical_repo.insert_mapping(
                ProductMapping(catalog_id=anchor.id, canonical_id=cid, similarity_score=1.0)
            )
            canonical_created += 1
            mappings_created += 1

        # Match other platform products to anchor canonical products
        unmapped_count = 0
        for platform, products in by_platform.items():
            product_texts = [
                self.embedder.compose_product_text(p.name, p.brand, normalize_unit(p.unit))
                for p in products
            ]

            matches = self.embedder.find_matches(
                product_texts, anchor_texts, threshold=AMBIGUOUS_LOWER_THRESHOLD
            )

            # Build best match per product
            best_matches: dict[int, tuple[int, float]] = {}
            for query_idx, corpus_idx, sim in matches:
                if query_idx not in best_matches or sim > best_matches[query_idx][1]:
                    best_matches[query_idx] = (corpus_idx, sim)

            for prod_idx, product in enumerate(products):
                if prod_idx in best_matches:
                    anchor_idx, sim = best_matches[prod_idx]
                    canonical_id = anchor_canonical_ids[anchor_idx]
                    self.canonical_repo.insert_mapping(
                        ProductMapping(
                            catalog_id=product.id,
                            canonical_id=canonical_id,
                            similarity_score=round(sim, 4),
                        )
                    )
                    mappings_created += 1
                else:
                    # No match — create new canonical product
                    canonical = CanonicalProduct(
                        canonical_name=product.name,
                        brand=product.brand,
                        category=category,
                        unit_normalized=normalize_unit(product.unit),
                    )
                    cid = self.canonical_repo.insert_canonical(canonical)
                    self.canonical_repo.insert_mapping(
                        ProductMapping(catalog_id=product.id, canonical_id=cid, similarity_score=1.0)
                    )
                    canonical_created += 1
                    mappings_created += 1
                    unmapped_count += 1

        return NormalizationResult(
            canonical_products_created=canonical_created,
            mappings_created=mappings_created,
            unmapped_count=unmapped_count,
        )

    async def _validate_match_with_llm(
        self, product_a: CatalogProduct, product_b: CatalogProduct, similarity: float
    ) -> bool:
        """Use Gemini to validate an ambiguous product match."""
        client = genai.Client(api_key=settings.google_api_key)
        response = await client.aio.models.generate_content(
            model=settings.normalizer_model,
            contents=(
                f"Are these the same product? Answer YES or NO only.\n"
                f"Product A: {product_a.name} ({product_a.brand}, {product_a.unit})\n"
                f"Product B: {product_b.name} ({product_b.brand}, {product_b.unit})\n"
                f"Similarity score: {similarity:.2f}"
            ),
            config=genai_types.GenerateContentConfig(max_output_tokens=10),
        )
        answer = response.text.strip().upper()
        return answer.startswith("YES")
