#!/usr/bin/env python3
"""One-shot: generate Gemini ground truth for LLM judge benchmark.

Queries all ambiguous pairs (0.80 <= sim < 0.85) from live DB,
calls Gemini for YES/NO verdicts, saves to data/eval/gemini_ground_truth.json.

Usage:
    python eval/generate_gemini_ground_truth.py
"""

import asyncio
import json
import logging
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.agents.normalizer import AMBIGUOUS_LOWER_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD
from src.config.settings import settings
from src.models.product import Platform

logging.basicConfig(level=logging.WARNING)

LIVE_DB_PATH = ROOT / "data" / "qc_intel.db"
OUTPUT_PATH = ROOT / "data" / "eval" / "gemini_ground_truth.json"

PROMPT_TEMPLATE = (
    "You are a product matching expert for Indian quick commerce platforms "
    "(Blinkit, Zepto, Instamart).\n\n"
    "Determine if these two product listings refer to the SAME physical product "
    "(same brand, same variant, same size/weight).\n\n"
    "Product A: {name_a} ({brand_a}, {unit_a})\n"
    "Product B: {name_b} ({brand_b}, {unit_b})\n"
    "Embedding similarity: {similarity:.2f}\n\n"
    "Rules:\n"
    "- Same brand + same variant + same size = YES\n"
    "- Different brand = NO\n"
    "- Same brand but different variant (e.g. 'Toned' vs 'Full Cream') = NO\n"
    "- Same brand but different size (e.g. '500ml' vs '1L') = NO\n"
    "- Minor name differences across platforms = YES if same product\n"
    "- Verbose or reworded listings that share the same brand + product line "
    "+ variant = YES (e.g. 'Sunfeast Dark Fantasy Bourbon' vs "
    "'Classic Bourbon Biscuits made with Real Chocolate by Sunfeast Dark Fantasy')\n"
    "- Different spellings of the same Indian product = YES "
    "(e.g. 'Sonamasuri'/'Sona Masoori', 'Atta'/'Aata', 'Paneer'/'Paner'). "
    "Ignore qualifiers like 'Raw' if the core product is the same\n"
    "- For produce: 'Desi', 'Local', 'Regular' are DIFFERENT variants — treat as NO\n\n"
    "Answer with ONLY 'YES' or 'NO'."
)


def collect_ambiguous_pairs(conn: sqlite3.Connection) -> list[dict]:
    """Pull all ambiguous pairs from live DB with their anchor products."""
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

    pairs = []
    for row in rows:
        anchor = conn.execute(
            """
            SELECT pc.name, pc.brand, pc.unit, pc.platform
            FROM product_mappings pm
            JOIN product_catalog pc ON pm.catalog_id = pc.id
            WHERE pm.canonical_id = ? AND pc.platform = 'blinkit'
            LIMIT 1
            """,
            (row[1],),
        ).fetchone()

        if not anchor:
            continue

        pairs.append({
            "pair_id": len(pairs),
            "catalog_id": row[0],
            "canonical_id": row[1],
            "similarity": round(row[2], 4),
            "name_a": anchor[0],
            "brand_a": anchor[1] or "",
            "unit_a": anchor[2] or "",
            "platform_a": anchor[3],
            "name_b": row[3],
            "brand_b": row[4] or "",
            "unit_b": row[5] or "",
            "platform_b": row[6],
        })

    return pairs


async def run_gemini(pairs: list[dict]) -> list[dict]:
    """Call Gemini on each pair, return pairs with verdicts attached."""
    from google import genai

    client = genai.Client(api_key=settings.google_api_key)
    results = []

    for i, pair in enumerate(pairs):
        prompt = PROMPT_TEMPLATE.format(**pair)
        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=genai.types.GenerateContentConfig(max_output_tokens=5),
            )
            answer = (response.text or "").strip().upper()
            verdict = "YES" if answer.startswith("YES") else "NO"
        except Exception as e:
            logging.warning("Gemini failed for pair %d: %s", pair["pair_id"], e)
            verdict = "ERROR"

        results.append({**pair, "gemini_verdict": verdict})

        if (i + 1) % 10 == 0 or i == len(pairs) - 1:
            print(f"\r  Progress: {i + 1}/{len(pairs)}", end="", flush=True)

    print()
    return results


def main() -> None:
    if not LIVE_DB_PATH.exists():
        print(f"Live DB not found at {LIVE_DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(LIVE_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    print("Collecting ambiguous pairs from live DB...")
    pairs = collect_ambiguous_pairs(conn)
    conn.close()

    if not pairs:
        print("No ambiguous pairs found.")
        sys.exit(0)

    print(f"Found {len(pairs)} ambiguous pairs (sim {AMBIGUOUS_LOWER_THRESHOLD:.2f}–{HIGH_CONFIDENCE_THRESHOLD:.2f})")
    print("Running Gemini ground truth collection...")
    results = asyncio.run(run_gemini(pairs))

    # Summary
    yes_count = sum(1 for r in results if r["gemini_verdict"] == "YES")
    no_count = sum(1 for r in results if r["gemini_verdict"] == "NO")
    err_count = sum(1 for r in results if r["gemini_verdict"] == "ERROR")
    print(f"\nVerdicts: {yes_count} YES, {no_count} NO" + (f", {err_count} ERROR" if err_count else ""))

    # Save
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "metadata": {
            "model": "gemini-2.5-flash",
            "similarity_range": [AMBIGUOUS_LOWER_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD],
            "total_pairs": len(results),
            "yes_count": yes_count,
            "no_count": no_count,
        },
        "pairs": results,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"Saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
