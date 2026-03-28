"""
QC Intel — Product Embedding Benchmark & Production Matcher

Runs on Kaggle T4 GPU. Two modes:
  1. Benchmark: tests 7 embedding model combos on fixture data
  2. Production: embeds + reranks using winning combo (bge-m3 + bge-reranker-v2-m3)

Input:  input/catalog.json
Output: benchmark_results.json, match_results.json
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# On Kaggle, datasets mount at /kaggle/input/<dataset-slug>/
INPUT_DIR = Path("/kaggle/input/qc-intel-catalog")
if not INPUT_DIR.exists():
    INPUT_DIR = Path("input")  # Local fallback
CATALOG_PATH = INPUT_DIR / "catalog.json"
FIXTURES_PATH = INPUT_DIR / "fixtures_catalog.json"  # Fixtures in same dataset
BENCHMARK_OUT = Path("benchmark_results.json")
MATCH_OUT = Path("match_results.json")

# ---------------------------------------------------------------------------
# Production model config (update after benchmark)
# ---------------------------------------------------------------------------
PROD_EMBEDDER = "BAAI/bge-m3"
PROD_RERANKER = "BAAI/bge-reranker-v2-m3"
COSINE_FLOOR = 0.4
TOP_K = 5

# ---------------------------------------------------------------------------
# Model combo definitions
# ---------------------------------------------------------------------------
COMBOS: list[dict[str, Any]] = [
    {
        "name": "MiniLM-L6-v2",
        "embedder": "sentence-transformers/all-MiniLM-L6-v2",
        "embedder_type": "sentence_transformers",
        "reranker": None,
        "sparse": False,
    },
    {
        "name": "bge-m3 dense",
        "embedder": "BAAI/bge-m3",
        "embedder_type": "flag_embedding",
        "reranker": None,
        "sparse": False,
    },
    {
        "name": "bge-m3 dense+sparse",
        "embedder": "BAAI/bge-m3",
        "embedder_type": "flag_embedding",
        "reranker": None,
        "sparse": True,
    },
    {
        "name": "bge-m3 + bge-reranker-v2-m3",
        "embedder": "BAAI/bge-m3",
        "embedder_type": "flag_embedding",
        "reranker": "BAAI/bge-reranker-v2-m3",
        "sparse": False,
    },
    {
        "name": "Qwen3-Embedding-0.6B",
        "embedder": "Qwen/Qwen3-Embedding-0.6B",
        "embedder_type": "sentence_transformers",
        "reranker": None,
        "sparse": False,
    },
    {
        "name": "Qwen3-Embedding-0.6B + bge-reranker-v2-m3",
        "embedder": "Qwen/Qwen3-Embedding-0.6B",
        "embedder_type": "sentence_transformers",
        "reranker": "BAAI/bge-reranker-v2-m3",
        "sparse": False,
    },
    {
        "name": "Vyakyarth",
        "embedder": "krutrim-ai-labs/Vyakyarth",
        "embedder_type": "sentence_transformers",
        "reranker": None,
        "sparse": False,
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between every row in a and every row in b."""
    a_norm = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-10)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-10)
    return a_norm @ b_norm.T


def get_top_k_candidates(
    sim_matrix: np.ndarray, k: int = 5, floor: float = 0.4
) -> list[list[tuple[int, int, float]]]:
    """For each query row, return top-k (query_idx, corpus_idx, score) above floor."""
    results: list[list[tuple[int, int, float]]] = []
    for qi in range(sim_matrix.shape[0]):
        row = sim_matrix[qi]
        idxs = np.argsort(row)[::-1]
        candidates: list[tuple[int, int, float]] = []
        for ci in idxs:
            score = float(row[ci])
            if score < floor:
                break
            candidates.append((qi, int(ci), score))
            if len(candidates) >= k:
                break
        results.append(candidates)
    return results


def rerank_candidates(
    reranker: Any,
    query_texts: list[str],
    corpus_texts: list[str],
    candidates: list[list[tuple[int, int, float]]],
) -> list[list[dict[str, Any]]]:
    """Rerank candidate pairs and return sorted results with both scores."""
    all_results: list[list[dict[str, Any]]] = []
    for qi_candidates in candidates:
        if not qi_candidates:
            all_results.append([])
            continue
        pairs = [
            [query_texts[qi], corpus_texts[ci]] for qi, ci, _ in qi_candidates
        ]
        rerank_scores = reranker.compute_score(pairs)
        if isinstance(rerank_scores, (int, float)):
            rerank_scores = [rerank_scores]
        scored = []
        for (qi, ci, dense_score), rs in zip(qi_candidates, rerank_scores):
            scored.append(
                {
                    "query_idx": qi,
                    "corpus_idx": ci,
                    "dense_score": round(float(dense_score), 4),
                    "rerank_score": round(float(rs), 4),
                }
            )
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        all_results.append(scored)
    return all_results


# ---------------------------------------------------------------------------
# Model loaders (lazy, cached)
# ---------------------------------------------------------------------------
_model_cache: dict[str, Any] = {}


def load_sentence_transformer(model_name: str) -> Any:
    if model_name in _model_cache:
        return _model_cache[model_name]
    from sentence_transformers import SentenceTransformer

    log.info("Loading SentenceTransformer: %s", model_name)
    model = SentenceTransformer(model_name)
    _model_cache[model_name] = model
    return model


def load_bge_m3(model_name: str = "BAAI/bge-m3") -> Any:
    if model_name in _model_cache:
        return _model_cache[model_name]
    from FlagEmbedding import BGEM3FlagModel

    log.info("Loading BGEM3FlagModel: %s", model_name)
    model = BGEM3FlagModel(model_name, use_fp16=True)
    _model_cache[model_name] = model
    return model


def load_reranker(model_name: str = "BAAI/bge-reranker-v2-m3") -> Any:
    if model_name in _model_cache:
        return _model_cache[model_name]
    from FlagEmbedding import FlagReranker

    log.info("Loading FlagReranker: %s", model_name)
    model = FlagReranker(model_name, use_fp16=True)
    _model_cache[model_name] = model
    return model


# ---------------------------------------------------------------------------
# Embedding dispatch
# ---------------------------------------------------------------------------


def embed_texts(
    texts: list[str],
    model_name: str,
    embedder_type: str,
    return_sparse: bool = False,
) -> dict[str, Any]:
    """Embed texts and return {'dense': np.ndarray, 'sparse': list | None}."""
    if embedder_type == "flag_embedding":
        model = load_bge_m3(model_name)
        output = model.encode(texts, return_dense=True, return_sparse=return_sparse)
        result: dict[str, Any] = {"dense": output["dense_vecs"]}
        if return_sparse:
            result["sparse"] = output["lexical_weights"]
        else:
            result["sparse"] = None
        return result
    else:
        model = load_sentence_transformer(model_name)
        dense = model.encode(texts, convert_to_numpy=True)
        return {"dense": dense, "sparse": None}


def compute_similarity(
    anchor_out: dict[str, Any],
    other_out: dict[str, Any],
    use_sparse: bool = False,
    bge_model: Any = None,
) -> np.ndarray:
    """Compute similarity matrix, optionally blending dense + sparse."""
    dense_sim = cosine_similarity_matrix(anchor_out["dense"], other_out["dense"])
    if not use_sparse or anchor_out["sparse"] is None:
        return dense_sim

    # Compute sparse scores pairwise
    n_anchor = len(anchor_out["sparse"])
    n_other = len(other_out["sparse"])
    sparse_sim = np.zeros((n_anchor, n_other), dtype=np.float32)
    for i in range(n_anchor):
        for j in range(n_other):
            sparse_sim[i, j] = bge_model.compute_lexical_matching_score(
                anchor_out["sparse"][i], other_out["sparse"][j]
            )
    # Blend: 0.7 * dense + 0.3 * sparse
    return 0.7 * dense_sim + 0.3 * sparse_sim


# ---------------------------------------------------------------------------
# Catalog loading
# ---------------------------------------------------------------------------


def load_catalog(path: Path) -> dict[str, Any]:
    log.info("Loading catalog from %s", path)
    with open(path) as f:
        return json.load(f)


def extract_texts(products: list[dict]) -> list[str]:
    """Extract embedding text from product dicts."""
    return [p.get("text", p.get("name", "")) for p in products]


def extract_ids(products: list[dict]) -> list[Any]:
    return [p.get("id", p.get("platform_product_id", i)) for i in range(len(products))]


# ---------------------------------------------------------------------------
# Benchmark mode
# ---------------------------------------------------------------------------


def run_benchmark(catalog: dict[str, Any]) -> dict[str, Any]:
    """Run all 7 combos on catalog data and return benchmark results."""
    log.info("=" * 60)
    log.info("BENCHMARK MODE")
    log.info("=" * 60)

    anchor_products = catalog["anchor_products"]
    other_products_by_platform = catalog.get("other_products", {})

    # Flatten all other-platform products into one corpus
    corpus_products: list[dict] = []
    for platform, products in other_products_by_platform.items():
        for p in products:
            p_copy = dict(p)
            p_copy.setdefault("platform", platform)
            corpus_products.append(p_copy)

    anchor_texts = extract_texts(anchor_products)
    corpus_texts = extract_texts(corpus_products)

    log.info(
        "Anchor products: %d, Corpus products: %d",
        len(anchor_texts),
        len(corpus_texts),
    )

    combo_results: list[dict[str, Any]] = []

    for combo in COMBOS:
        name = combo["name"]
        log.info("-" * 40)
        log.info("Combo: %s", name)
        t0 = time.time()

        try:
            # Embed
            anchor_out = embed_texts(
                anchor_texts,
                combo["embedder"],
                combo["embedder_type"],
                return_sparse=combo["sparse"],
            )
            corpus_out = embed_texts(
                corpus_texts,
                combo["embedder"],
                combo["embedder_type"],
                return_sparse=combo["sparse"],
            )

            # Similarity — corpus × anchor so each row = one non-anchor product
            bge_model = None
            if combo["sparse"]:
                bge_model = _model_cache.get(combo["embedder"])
            sim_matrix = compute_similarity(
                corpus_out, anchor_out, use_sparse=combo["sparse"], bge_model=bge_model
            )

            # Top-k candidates
            candidates = get_top_k_candidates(sim_matrix, k=TOP_K, floor=COSINE_FLOOR)

            # Optional reranking — query=corpus(non-anchor), corpus=anchor
            if combo["reranker"]:
                reranker_model = load_reranker(combo["reranker"])
                reranked = rerank_candidates(
                    reranker_model, corpus_texts, anchor_texts, candidates
                )
                scores = []
                for qi_results in reranked:
                    for r in qi_results:
                        qi, ci = r["query_idx"], r["corpus_idx"]
                        scores.append(
                            {
                                "query_id": extract_ids(corpus_products)[qi],
                                "corpus_id": extract_ids(anchor_products)[ci],
                                "dense_score": r["dense_score"],
                                "rerank_score": r["rerank_score"],
                                "query_text": corpus_texts[qi],
                                "corpus_text": anchor_texts[ci],
                            }
                        )
            else:
                scores = []
                for qi_candidates in candidates:
                    for qi, ci, score in qi_candidates:
                        scores.append(
                            {
                                "query_id": extract_ids(corpus_products)[qi],
                                "corpus_id": extract_ids(anchor_products)[ci],
                                "score": round(score, 4),
                                "query_text": corpus_texts[qi],
                                "corpus_text": anchor_texts[ci],
                            }
                        )

            elapsed = time.time() - t0
            log.info("  Done in %.1fs — %d scored pairs", elapsed, len(scores))

            combo_results.append(
                {
                    "name": name,
                    "embedder": combo["embedder"],
                    "reranker": combo["reranker"],
                    "elapsed_seconds": round(elapsed, 1),
                    "num_scores": len(scores),
                    "scores": scores,
                }
            )

        except Exception as e:
            elapsed = time.time() - t0
            log.error("  FAILED after %.1fs: %s", elapsed, e)
            combo_results.append(
                {
                    "name": name,
                    "embedder": combo["embedder"],
                    "reranker": combo["reranker"],
                    "error": str(e),
                    "elapsed_seconds": round(elapsed, 1),
                }
            )

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "anchor_count": len(anchor_products),
        "corpus_count": len(corpus_products),
        "combos": combo_results,
    }
    return result


# ---------------------------------------------------------------------------
# Production mode
# ---------------------------------------------------------------------------


def run_production(catalog: dict[str, Any]) -> dict[str, Any]:
    """Run production embedding + reranking with the winning combo."""
    log.info("=" * 60)
    log.info("PRODUCTION MODE — %s + %s", PROD_EMBEDDER, PROD_RERANKER)
    log.info("=" * 60)

    anchor_products = catalog["anchor_products"]
    other_products_by_platform = catalog.get("other_products", {})

    corpus_products: list[dict] = []
    for platform, products in other_products_by_platform.items():
        for p in products:
            p_copy = dict(p)
            p_copy.setdefault("platform", platform)
            corpus_products.append(p_copy)

    anchor_texts = extract_texts(anchor_products)
    corpus_texts = extract_texts(corpus_products)

    log.info(
        "Anchor products: %d, Corpus products: %d",
        len(anchor_texts),
        len(corpus_texts),
    )

    # Embed with bge-m3
    t0 = time.time()
    anchor_out = embed_texts(anchor_texts, PROD_EMBEDDER, "flag_embedding")
    corpus_out = embed_texts(corpus_texts, PROD_EMBEDDER, "flag_embedding")
    log.info("Embedding done in %.1fs", time.time() - t0)

    # Cosine similarity -> top-k candidates (corpus × anchor so each row = non-anchor product)
    sim_matrix = cosine_similarity_matrix(corpus_out["dense"], anchor_out["dense"])
    candidates = get_top_k_candidates(sim_matrix, k=TOP_K, floor=COSINE_FLOOR)

    # Rerank — query=corpus(non-anchor), corpus=anchor
    t1 = time.time()
    reranker_model = load_reranker(PROD_RERANKER)
    reranked = rerank_candidates(reranker_model, corpus_texts, anchor_texts, candidates)
    log.info("Reranking done in %.1fs", time.time() - t1)

    # Build output — query=non-anchor product, corpus=anchor product
    matches: list[dict[str, Any]] = []
    anchor_ids = extract_ids(anchor_products)
    corpus_ids = extract_ids(corpus_products)

    for qi_results in reranked:
        for r in qi_results:
            qi, ci = r["query_idx"], r["corpus_idx"]
            matches.append(
                {
                    "query_id": corpus_ids[qi],
                    "query_text": corpus_texts[qi],
                    "corpus_id": anchor_ids[ci],
                    "corpus_text": anchor_texts[ci],
                    "dense_score": r["dense_score"],
                    "rerank_score": r["rerank_score"],
                }
            )

    # Sort by rerank score descending
    matches.sort(key=lambda x: x["rerank_score"], reverse=True)

    result = {
        "model": PROD_EMBEDDER,
        "reranker": PROD_RERANKER,
        "category": catalog.get("category", "unknown"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "anchor_platform": catalog.get("anchor_platform", "unknown"),
        "num_matches": len(matches),
        "matches": matches,
    }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    log.info("QC Intel — Embedding Benchmark & Production Matcher")
    log.info("GPU available: %s", os.environ.get("CUDA_VISIBLE_DEVICES", "not set"))

    # Try to detect GPU
    try:
        import torch

        log.info("PyTorch CUDA: %s (devices: %d)", torch.cuda.is_available(), torch.cuda.device_count())
        if torch.cuda.is_available():
            log.info("GPU: %s", torch.cuda.get_device_name(0))
    except ImportError:
        log.warning("PyTorch not available — running on CPU")

    # Load catalog
    if not CATALOG_PATH.exists():
        log.error("Catalog not found at %s", CATALOG_PATH)
        return
    catalog = load_catalog(CATALOG_PATH)

    total_start = time.time()

    # Benchmark mode — runs if fixtures file exists
    if FIXTURES_PATH.exists():
        log.info("Fixtures found at %s — running benchmark mode", FIXTURES_PATH)
        fixture_catalog = load_catalog(FIXTURES_PATH)
        benchmark = run_benchmark(fixture_catalog)
        with open(BENCHMARK_OUT, "w") as f:
            json.dump(benchmark, f, indent=2)
        log.info("Benchmark results written to %s", BENCHMARK_OUT)

        # Print summary table
        log.info("")
        log.info("%-45s %8s %8s", "Combo", "Pairs", "Time(s)")
        log.info("-" * 65)
        for c in benchmark["combos"]:
            if "error" in c:
                log.info("%-45s %8s %8.1f", c["name"], "FAILED", c["elapsed_seconds"])
            else:
                log.info("%-45s %8d %8.1f", c["name"], c["num_scores"], c["elapsed_seconds"])
    else:
        log.info("No fixtures file found — skipping benchmark mode")

    # Production mode — always runs
    try:
        production = run_production(catalog)
        with open(MATCH_OUT, "w") as f:
            json.dump(production, f, indent=2)
        log.info("Production results written to %s (%d matches)", MATCH_OUT, production["num_matches"])
    except Exception as e:
        log.error("Production mode failed: %s", e)
        raise

    total_elapsed = time.time() - total_start
    log.info("Total runtime: %.1fs (%.1f min)", total_elapsed, total_elapsed / 60)


if __name__ == "__main__":
    main()
