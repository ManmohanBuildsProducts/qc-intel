"""Normalizer agent — cross-platform product matching via Kaggle embeddings + reranker."""

import logging
import sqlite3

from google import genai
from google.genai import types as genai_types

from src.config.settings import settings
from src.db.repository import CanonicalRepository
from src.embeddings.kaggle_client import KaggleEmbeddingClient
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

# Thresholds (calibrated for bge-m3 dense scores)
HIGH_CONFIDENCE_THRESHOLD = 0.85
AMBIGUOUS_LOWER_THRESHOLD = 0.80
MRP_TOLERANCE_PCT = 15.0  # reject matches where MRP differs by more than 15%


class NormalizerService:
    """Cross-platform product normalization using pre-computed Kaggle embeddings."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.canonical_repo = CanonicalRepository(conn)
        self.embedder = ProductEmbedder()
        self.kaggle_client = KaggleEmbeddingClient()
        self._mrp_cache: dict[int, float | None] = {}

    def _get_latest_mrp(self, catalog_id: int) -> float | None:
        """Get the most recent MRP for a catalog product. Cached per session."""
        if catalog_id in self._mrp_cache:
            return self._mrp_cache[catalog_id]
        row = self.conn.execute(
            """SELECT mrp FROM product_observations
               WHERE catalog_id = ? AND mrp > 0
               ORDER BY observed_at DESC LIMIT 1""",
            (catalog_id,),
        ).fetchone()
        mrp = row[0] if row else None
        self._mrp_cache[catalog_id] = mrp
        return mrp

    def _mrp_compatible(self, catalog_id_a: int, catalog_id_b: int) -> bool:
        """Check if two products have compatible MRPs (within tolerance).

        Returns True if MRPs match within MRP_TOLERANCE_PCT, or if either MRP is missing.
        """
        mrp_a = self._get_latest_mrp(catalog_id_a)
        mrp_b = self._get_latest_mrp(catalog_id_b)
        if mrp_a is None or mrp_b is None:
            return True  # Can't verify — allow match
        min_mrp = min(mrp_a, mrp_b)
        if min_mrp == 0:
            return True
        pct_diff = abs(mrp_a - mrp_b) / min_mrp * 100
        return pct_diff <= MRP_TOLERANCE_PCT

    def normalize_category(
        self,
        category: str,
        match_results: dict | None = None,
    ) -> NormalizationResult:
        """Match products across platforms for a category. Blinkit = anchor platform.

        Args:
            category: Product category to normalize.
            match_results: Pre-computed match results from Kaggle. If None,
                          attempts to load from cache.
        """
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
            first_platform = next(iter(by_platform))
            anchor_products = by_platform.pop(first_platform)

        # Create canonical products for all anchor products
        canonical_created = 0
        mappings_created = 0
        anchor_canonical_ids: dict[int, int] = {}  # catalog_id -> canonical_id

        for anchor in anchor_products:
            canonical = CanonicalProduct(
                canonical_name=anchor.name,
                brand=anchor.brand,
                category=category,
                unit_normalized=normalize_unit(anchor.unit),
            )
            cid = self.canonical_repo.insert_canonical(canonical)
            anchor_canonical_ids[anchor.id] = cid
            self.canonical_repo.insert_mapping(
                ProductMapping(catalog_id=anchor.id, canonical_id=cid, similarity_score=1.0)
            )
            canonical_created += 1
            mappings_created += 1

        # Load match results (pre-computed by Kaggle)
        if match_results is None:
            match_results = self.kaggle_client.load_match_results(category)

        if match_results is None:
            # No match results available — all non-anchor products become new canonicals
            logger.warning("No match results for %s — creating new canonicals for all", category)
            for platform, products in by_platform.items():
                for product in products:
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
            return NormalizationResult(
                canonical_products_created=canonical_created,
                mappings_created=mappings_created,
                unmapped_count=sum(len(p) for p in by_platform.values()),
            )

        # Build match lookup: query_id (non-anchor) -> best (anchor_id, score)
        matches = self.embedder.find_matches_from_results(
            match_results, threshold=AMBIGUOUS_LOWER_THRESHOLD
        )

        best_matches: dict[int, tuple[int, float]] = {}
        for query_id, corpus_id, score in matches:
            if query_id not in best_matches or score > best_matches[query_id][1]:
                best_matches[query_id] = (corpus_id, score)

        # Build anchor lookup for unit checks
        anchor_by_id: dict[int, CatalogProduct] = {a.id: a for a in anchor_products}

        # Match other platform products
        unmapped_count = 0
        for platform, products in by_platform.items():
            for product in products:
                matched = False

                if product.id in best_matches:
                    anchor_id, sim = best_matches[product.id]
                    anchor = anchor_by_id.get(anchor_id)
                    reject_reason = None

                    if anchor:
                        # Guard 1: Unit mismatch
                        anchor_unit = normalize_unit(anchor.unit)
                        product_unit = normalize_unit(product.unit)
                        if anchor_unit and product_unit and anchor_unit != product_unit:
                            reject_reason = f"unit mismatch ({anchor_unit} vs {product_unit})"

                        # Guard 2: MRP mismatch
                        if not reject_reason and not self._mrp_compatible(anchor.id, product.id):
                            mrp_a = self._get_latest_mrp(anchor.id)
                            mrp_b = self._get_latest_mrp(product.id)
                            reject_reason = f"MRP mismatch (₹{mrp_a:.0f} vs ₹{mrp_b:.0f})"

                    if reject_reason:
                        logger.debug(
                            "Rejecting merge: %s vs %s — %s",
                            anchor.name if anchor else "?", product.name, reject_reason,
                        )
                    else:
                        canonical_id = anchor_canonical_ids.get(anchor_id)
                        if canonical_id:
                            self.canonical_repo.insert_mapping(
                                ProductMapping(
                                    catalog_id=product.id,
                                    canonical_id=canonical_id,
                                    similarity_score=round(sim, 4),
                                )
                            )
                            mappings_created += 1
                            matched = True

                if not matched:
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
            config=genai_types.GenerateContentConfig(max_output_tokens=200),
        )
        answer = (response.text or "").strip().upper()
        return answer.startswith("YES")
