#!/usr/bin/env python3
"""Automated normalization eval harness — three strategies, one report.

Usage:
    python eval/eval_normalization.py              # All three strategies
    python eval/eval_normalization.py --fast       # Rule-based only (no LLM)
    python eval/eval_normalization.py --sweep      # Threshold sweep (Strategy 1)
    python eval/eval_normalization.py --llm-judge  # LLM judge on live DB (Strategy 2)
    python eval/eval_normalization.py --llm-judge --fix  # + delete bad mappings
"""

import argparse
import asyncio
import json
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.normalizer import AMBIGUOUS_LOWER_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD, NormalizerService
from src.agents.scraper.service import ScrapeService
from src.db.init_db import init_db
from src.db.repository import CatalogRepository
from src.embeddings.product_embedder import ProductEmbedder
from src.embeddings.unit_normalizer import normalize_unit
from src.models.product import CatalogProduct, Platform, TimeOfDay

logging.basicConfig(level=logging.WARNING)

_SKIP = object()  # Sentinel: strategy was not requested

FIXTURES_DIR = ROOT / "tests" / "fixtures"
LIVE_DB_PATH = ROOT / "data" / "qc_intel.db"
CATEGORY = "Dairy & Bread"
PINCODE = "122001"

# Hardcoded ground truth from fixture inspection:
# blinkit_platform_product_id → zepto_product_id / instamart_product_id
# Only pairs that are truly the same product (same brand, same item type, same size)
GROUND_TRUTH_BL_ZP: set[tuple[str, str]] = {
    ("39868", "z-31001"),  # Amul Taaza Toned Milk 500ml
    ("39870", "z-31002"),  # Mother Dairy Full Cream Milk 500ml
    ("41200", "z-31003"),  # Amul Gold Full Cream Milk 500ml
    ("42100", "z-31010"),  # Amul Masti Dahi 400g
    ("42200", "z-31011"),  # Mother Dairy Classic Curd 400g
    ("43000", "z-31020"),  # Amul Butter 100g
    ("43500", "z-31030"),  # Britannia Cheese Slices 200g
    ("44000", "z-31040"),  # Amul Paneer 200g
    ("44500", "z-31050"),  # Nestle A+ Nourish Toned Milk 1L
    # blinkit 45000 (Harvest Gold) ≠ zepto z-31060 (English Oven) — different brands
}

GROUND_TRUTH_BL_IM: set[tuple[str, str]] = {
    ("39868", "im-5001"),  # Amul Taaza Toned Milk 500ml
    ("39870", "im-5002"),  # Mother Dairy Full Cream Milk 500ml
    ("41200", "im-5003"),  # Amul Gold Milk 500ml
    ("42100", "im-5010"),  # Amul Masti Dahi 400g
    ("42200", "im-5011"),  # Mother Dairy Curd 400g
    ("43000", "im-5020"),  # Amul Butter 100g
    ("43500", "im-5030"),  # Britannia Cheese Slices 200g
    ("44000", "im-5040"),  # Amul Paneer 200g
    # blinkit 44500 (Nestle) ≠ im-5050 (Verka Lassi) — different product
    # blinkit 45000 (Harvest Gold) ≠ im-5060 (Modern Multigrain) — different brands
}

GROUND_TRUTH_ALL: set[tuple[str, str]] = GROUND_TRUTH_BL_ZP | GROUND_TRUTH_BL_IM


def _seed_fixtures(conn: sqlite3.Connection) -> None:
    """Load all three fixture files into the given DB connection."""
    svc = ScrapeService(conn)
    for platform, fname in [
        (Platform.BLINKIT, "blinkit_dairy.json"),
        (Platform.ZEPTO, "zepto_dairy.json"),
        (Platform.INSTAMART, "instamart_dairy.json"),
    ]:
        data = json.loads((FIXTURES_DIR / fname).read_text())
        svc.process_scrape_results(data, platform, PINCODE, CATEGORY, TimeOfDay.MORNING)


def _build_actual_pairs_from_sim(
    blinkit_prods: list[CatalogProduct],
    other_prods: list[CatalogProduct],
    sim_matrix,  # shape: [len(other), len(blinkit)]
    threshold: float,
) -> set[tuple[str, str]]:
    """Greedy best-match: each non-blinkit product claims its best blinkit match above threshold."""
    pairs: set[tuple[str, str]] = set()
    for i, prod in enumerate(other_prods):
        best_score = -1.0
        best_j = -1
        for j in range(len(blinkit_prods)):
            if sim_matrix[i][j] >= threshold and sim_matrix[i][j] > best_score:
                best_score = sim_matrix[i][j]
                best_j = j
        if best_j >= 0:
            pairs.add((blinkit_prods[best_j].platform_product_id, prod.platform_product_id))
    return pairs


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def strategy1_sweep(thresholds: list[float]) -> list[dict]:
    """Fixture ground truth with threshold sweep. Single embedding pass."""
    conn = init_db(":memory:")
    conn.row_factory = sqlite3.Row
    _seed_fixtures(conn)

    cat_repo = CatalogRepository(conn)
    blinkit = cat_repo.get_by_platform(Platform.BLINKIT)
    zepto = cat_repo.get_by_platform(Platform.ZEPTO)
    instamart = cat_repo.get_by_platform(Platform.INSTAMART)
    conn.close()

    embedder = ProductEmbedder()

    def texts(prods: list[CatalogProduct]) -> list[str]:
        return [embedder.compose_product_text(p.name, p.brand, normalize_unit(p.unit)) for p in prods]

    bl_texts = texts(blinkit)
    zp_texts = texts(zepto)
    im_texts = texts(instamart)

    # Compute similarity matrices once: [other × blinkit]
    sim_zp = embedder.similarity_matrix(zp_texts, bl_texts)
    sim_im = embedder.similarity_matrix(im_texts, bl_texts)

    results = []
    for t in thresholds:
        actual = _build_actual_pairs_from_sim(blinkit, zepto, sim_zp, t) | \
                 _build_actual_pairs_from_sim(blinkit, instamart, sim_im, t)
        tp = len(GROUND_TRUTH_ALL & actual)
        fp = len(actual - GROUND_TRUTH_ALL)
        fn = len(GROUND_TRUTH_ALL - actual)
        p, r, f1 = _prf(tp, fp, fn)
        results.append({"threshold": t, "precision": p, "recall": r, "f1": f1, "tp": tp, "fp": fp, "fn": fn})

    return results


async def strategy2_llm_judge(fix: bool = False) -> dict | None:
    """LLM judge on live DB ambiguous pairs (0.70 <= sim < 0.85)."""
    if not LIVE_DB_PATH.exists():
        return None

    conn = sqlite3.connect(str(LIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    rows = conn.execute(
        """
        SELECT
            pm.catalog_id, pm.canonical_id, pm.similarity_score,
            pc.name, pc.brand, pc.unit, pc.platform, pc.subcategory
        FROM product_mappings pm
        JOIN product_catalog pc ON pm.catalog_id = pc.id
        WHERE pm.similarity_score >= ? AND pm.similarity_score < ?
        ORDER BY pm.similarity_score DESC
        """,
        (AMBIGUOUS_LOWER_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD),
    ).fetchall()

    if not rows:
        conn.close()
        return {"total": 0, "verified": 0, "rejected": []}

    # For each ambiguous product, find its anchor (blinkit product in same canonical)
    normalizer = NormalizerService(conn)
    semaphore = asyncio.Semaphore(5)

    async def validate_row(row) -> tuple[bool, dict]:
        anchor_row = conn.execute(
            """
            SELECT pc.id, pc.name, pc.brand, pc.unit, pc.platform, pc.category, pc.subcategory,
                   pc.platform_product_id
            FROM product_mappings pm
            JOIN product_catalog pc ON pm.catalog_id = pc.id
            WHERE pm.canonical_id = ? AND pc.platform = 'blinkit'
            LIMIT 1
            """,
            (row["canonical_id"],),
        ).fetchone()

        if not anchor_row:
            # No blinkit anchor found — skip
            return True, {}

        product_a = CatalogProduct(
            id=anchor_row[0],
            platform=Platform(anchor_row[4]),
            platform_product_id=anchor_row[7],
            name=anchor_row[1],
            brand=anchor_row[2],
            category=anchor_row[5],
            subcategory=anchor_row[6],
            unit=anchor_row[3],
        )
        product_b = CatalogProduct(
            id=row["catalog_id"],
            platform=Platform(row["platform"]),
            platform_product_id=str(row["catalog_id"]),
            name=row["name"],
            brand=row["brand"],
            category=CATEGORY,
            subcategory=row["subcategory"],
            unit=row["unit"],
        )

        async with semaphore:
            is_valid = await normalizer._validate_match_with_llm(product_a, product_b, row["similarity_score"])

        info = {
            "catalog_id": row["catalog_id"],
            "canonical_id": row["canonical_id"],
            "similarity": row["similarity_score"],
            "product_a": f"{product_a.brand} {product_a.name} ({product_a.unit})",
            "product_b": f"{product_b.brand} {product_b.name} ({product_b.unit})",
        }
        return is_valid, info

    tasks = [validate_row(row) for row in rows]
    results = await asyncio.gather(*tasks)

    verified = sum(1 for ok, _ in results if ok)
    rejected = [info for ok, info in results if not ok and info]

    if fix and rejected:
        for info in rejected:
            conn.execute(
                "DELETE FROM product_mappings WHERE catalog_id = ?",
                (info["catalog_id"],),
            )
        conn.commit()

    conn.close()

    return {
        "total": len(rows),
        "verified": verified,
        "rejected": rejected,
        "fixed": fix,
    }


def _jaccard(a: str, b: str) -> float:
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def strategy3_rule_based(conn: sqlite3.Connection) -> dict:
    """Rule-based quality checks on a DB connection."""
    # --- Check 1: Oversized clusters (>3 mappings = >1 per platform) ---
    oversized = conn.execute(
        """
        SELECT canonical_id, COUNT(*) as cnt
        FROM product_mappings
        GROUP BY canonical_id
        HAVING COUNT(*) > 3
        """
    ).fetchall()

    # --- Check 2: Unit conflicts within canonical clusters ---
    cluster_rows = conn.execute(
        """
        SELECT cp.id, cp.canonical_name, cp.brand, pc.unit
        FROM canonical_products cp
        JOIN product_mappings pm ON cp.id = pm.canonical_id
        JOIN product_catalog pc ON pm.catalog_id = pc.id
        """
    ).fetchall()

    # Group units per canonical
    canonical_units: dict[int, set[str]] = {}
    canonical_names: dict[int, str] = {}
    for row in cluster_rows:
        cid = row[0]
        raw_unit = row[3]
        if raw_unit:
            norm = normalize_unit(raw_unit)
            if norm:
                canonical_units.setdefault(cid, set()).add(norm)
                canonical_names[cid] = f"{row[2] or ''} {row[1]}".strip()

    unit_conflicts = [
        {"canonical_id": cid, "name": canonical_names[cid], "units": sorted(units)}
        for cid, units in canonical_units.items()
        if len(units) > 1
    ]

    # --- Check 3: Low Jaccard matches (cosine sim > 0.70 but token overlap < 0.30) ---
    cross_platform_rows = conn.execute(
        """
        SELECT
            pc_bl.name as bl_name, pc_bl.brand as bl_brand,
            pc_other.name as other_name, pc_other.brand as other_brand,
            pm_other.similarity_score, pm_other.canonical_id
        FROM product_mappings pm_bl
        JOIN product_catalog pc_bl ON pm_bl.catalog_id = pc_bl.id
        JOIN product_mappings pm_other ON pm_bl.canonical_id = pm_other.canonical_id
            AND pm_other.catalog_id != pm_bl.catalog_id
        JOIN product_catalog pc_other ON pm_other.catalog_id = pc_other.id
        WHERE pc_bl.platform = 'blinkit'
          AND pm_other.similarity_score >= ?
          AND pm_other.similarity_score < 1.0
        """,
        (AMBIGUOUS_LOWER_THRESHOLD,),
    ).fetchall()

    low_jaccard = []
    seen_pairs: set[tuple] = set()
    for row in cross_platform_rows:
        pair_key = (row[5], row[2])  # (canonical_id, other_name) — deduplicate
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        jac = _jaccard(
            f"{row[1] or ''} {row[0]}",
            f"{row[3] or ''} {row[2]}",
        )
        if jac < 0.30:
            low_jaccard.append({
                "blinkit": f"{row[1] or ''} {row[0]}".strip(),
                "other": f"{row[3] or ''} {row[2]}".strip(),
                "similarity": row[4],
                "jaccard": round(jac, 3),
            })

    # Total canonical count
    total_canonicals = conn.execute("SELECT COUNT(*) FROM canonical_products").fetchone()[0]

    return {
        "unit_conflicts": unit_conflicts,
        "oversized_clusters": [{"canonical_id": r[0], "count": r[1]} for r in oversized],
        "low_jaccard": low_jaccard,
        "total_canonicals": total_canonicals,
    }


def print_report(
    sweep_results,  # list[dict] | None | _SKIP
    llm_results,    # dict | None (DB not found) | _SKIP (not requested)
    rule_results,   # dict | None | _SKIP
) -> None:
    print()
    print("=" * 50)
    print("    NORMALIZATION EVAL REPORT")
    print("=" * 50)

    if sweep_results is not None and sweep_results is not _SKIP:
        print()
        print("[Strategy 1 — Fixture Ground Truth]")
        print(f"  Ground truth pairs: {len(GROUND_TRUTH_ALL)} (9 blinkit-zepto, 8 blinkit-instamart)")
        print()
        print(f"  {'Threshold':>10}  {'Precision':>10}  {'Recall':>8}  {'F1':>8}  {'TP':>4}  {'FP':>4}  {'FN':>4}")
        print("  " + "-" * 60)
        current_threshold = AMBIGUOUS_LOWER_THRESHOLD
        for r in sweep_results:
            marker = " ← current" if abs(r["threshold"] - current_threshold) < 0.001 else ""
            print(
                f"  {r['threshold']:>10.2f}  {r['precision']:>10.3f}  {r['recall']:>8.3f}"
                f"  {r['f1']:>8.3f}  {r['tp']:>4}  {r['fp']:>4}  {r['fn']:>4}{marker}"
            )

        # Recommendation: threshold with best F1
        best = max(sweep_results, key=lambda x: x["f1"])
        current = next((r for r in sweep_results if abs(r["threshold"] - current_threshold) < 0.001), None)
        if best and current and best["threshold"] != current_threshold:
            print()
            print(f"  Recommended threshold: {best['threshold']:.2f} (F1={best['f1']:.3f})")
            prec_gain = (best["precision"] - current["precision"]) * 100
            rec_loss = (current["recall"] - best["recall"]) * 100
            print(f"  vs current {current_threshold:.2f}: +{prec_gain:.1f}% precision, -{rec_loss:.1f}% recall")

    if llm_results is not _SKIP:
        print()
        print("[Strategy 2 — LLM Judge (production DB)]")
        if llm_results is None:
            print(f"  Skipped (live DB not found at {LIVE_DB_PATH})")
        elif llm_results.get("total", 0) == 0:
            print("  No ambiguous pairs found in live DB.")
        else:
            total = llm_results["total"]
            verified = llm_results["verified"]
            rejected = llm_results.get("rejected", [])
            pct = verified / total * 100 if total > 0 else 0
            print(f"  Ambiguous pairs (0.70–{HIGH_CONFIDENCE_THRESHOLD:.2f}): {total}")
            print(f"  Verified correct by Gemini: {verified}/{total} = {pct:.1f}% precision")
            if rejected:
                print(f"  Bad matches: {len(rejected)}")
                for r in rejected[:5]:  # Show max 5 examples
                    print(f"    sim={r['similarity']:.3f}  {r['product_a']}  ↔  {r['product_b']}")
                if len(rejected) > 5:
                    print(f"    ... and {len(rejected) - 5} more")
                if llm_results.get("fixed"):
                    print(f"  Deleted {len(rejected)} bad mappings from DB (--fix applied).")
                else:
                    print("  Run with --fix to delete bad mappings.")

    if rule_results is not None and rule_results is not _SKIP:
        print()
        print("[Strategy 3 — Rule-based checks]")
        total_canonicals = rule_results["total_canonicals"]
        n_conflicts = len(rule_results["unit_conflicts"])
        n_oversized = len(rule_results["oversized_clusters"])
        n_low_jac = len(rule_results["low_jaccard"])
        total_flagged = n_conflicts + n_oversized + n_low_jac

        print(f"  Unit conflicts:           {n_conflicts} canonical clusters")
        if rule_results["unit_conflicts"]:
            for item in rule_results["unit_conflicts"][:3]:
                print(f"    canonical_id={item['canonical_id']} {item['name']}: {item['units']}")
        print(f"  Oversized clusters (>3):  {n_oversized}")
        if rule_results["oversized_clusters"]:
            for item in rule_results["oversized_clusters"][:3]:
                print(f"    canonical_id={item['canonical_id']}: {item['count']} mappings")
        print(f"  Low Jaccard (<0.30):      {n_low_jac} pairs")
        if rule_results["low_jaccard"]:
            for item in rule_results["low_jaccard"][:3]:
                print(f"    sim={item['similarity']:.3f} jac={item['jaccard']}  {item['blinkit']}  ↔  {item['other']}")
        if total_canonicals > 0:
            pct_flagged = total_flagged / total_canonicals * 100
            print(f"  Total flagged: {total_flagged} / {total_canonicals} canonicals ({pct_flagged:.1f}%)")
        else:
            print("  (No canonical products in DB)")

    print()
    print("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalization eval harness")
    parser.add_argument("--fast", action="store_true", help="Rule-based checks only (no LLM)")
    parser.add_argument("--sweep", action="store_true", help="Threshold sweep only (Strategy 1)")
    parser.add_argument("--llm-judge", action="store_true", help="Run LLM judge on live DB (Strategy 2)")
    parser.add_argument("--fix", action="store_true", help="With --llm-judge: delete rejected mappings")
    args = parser.parse_args()

    run_all = not (args.fast or args.sweep or args.llm_judge)
    thresholds = [0.70, 0.75, 0.80, 0.85, 0.90]

    sweep_results = _SKIP
    llm_results = _SKIP
    rule_results = _SKIP

    # Strategy 1: fixture sweep
    if run_all or args.sweep:
        print("Running Strategy 1: fixture sweep...", end=" ", flush=True)
        sweep_results = strategy1_sweep(thresholds)
        print("done")

    # Strategy 2: LLM judge on live DB
    if run_all or args.llm_judge:
        if not LIVE_DB_PATH.exists():
            print(f"Strategy 2: live DB not found at {LIVE_DB_PATH}, skipping.")
            llm_results = None
        else:
            print(f"Running Strategy 2: LLM judge on {LIVE_DB_PATH}...", end=" ", flush=True)
            llm_results = asyncio.run(strategy2_llm_judge(fix=args.fix))
            print("done")

    # Strategy 3: rule-based on live DB (or fixture DB if no live)
    if run_all or args.fast:
        if LIVE_DB_PATH.exists():
            conn = sqlite3.connect(str(LIVE_DB_PATH))
            conn.row_factory = sqlite3.Row
        else:
            print("Strategy 3: live DB not found, running on fixture data.")
            conn = init_db(":memory:")
            conn.row_factory = sqlite3.Row
            _seed_fixtures(conn)
            # Run normalization so there's something to check
            norm_svc = NormalizerService(conn)
            norm_svc.normalize_category(CATEGORY)

        print("Running Strategy 3: rule-based checks...", end=" ", flush=True)
        rule_results = strategy3_rule_based(conn)
        conn.close()
        print("done")

    print_report(sweep_results, llm_results, rule_results)


if __name__ == "__main__":
    main()
