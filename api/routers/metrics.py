"""Brand metrics endpoint — competitive analytics for brand managers."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from api.deps import get_db
from api.models import ApiResponse

router = APIRouter()


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Return the p-th percentile (0–100) of a sorted list."""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


def _histogram_8(prices: list[float], cat_min: float, cat_max: float) -> list[int]:
    """Bucket prices into 8 equal-width bins across [cat_min, cat_max]."""
    counts = [0] * 8
    if cat_min == cat_max or not prices:
        return counts
    width = (cat_max - cat_min) / 8
    for p in prices:
        idx = int((p - cat_min) / width)
        idx = min(idx, 7)  # last bin is inclusive of max
        counts[idx] += 1
    return counts


@router.get("/brand/{brand}/metrics")
def brand_metrics(
    brand: str,
    category: str = Query(...),
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    # ── 1. All SKUs in category ───────────────────────────────────────────────
    cat_rows = conn.execute(
        "SELECT pc.id, pc.platform, pc.brand, po.price, po.mrp "
        "FROM product_catalog pc "
        "LEFT JOIN ("
        "  SELECT catalog_id, price, mrp "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON pc.id = po.catalog_id "
        "WHERE pc.category = ?",
        [category],
    ).fetchall()

    brand_rows = [r for r in cat_rows if r["brand"] == brand]

    # ── 2. Share ──────────────────────────────────────────────────────────────
    category_total = len(cat_rows)
    sku_count = len(brand_rows)
    share_pct = (sku_count / category_total * 100) if category_total else 0.0

    # Rank: count brands with more SKUs than the target brand
    brand_counts: dict[str, int] = {}
    for r in cat_rows:
        if r["brand"]:
            brand_counts[r["brand"]] = brand_counts.get(r["brand"], 0) + 1
    target_count = brand_counts.get(brand, 0)
    rank = sum(1 for c in brand_counts.values() if c > target_count) + 1

    share = {
        "sku_count": sku_count,
        "category_total": category_total,
        "share_pct": round(share_pct, 2),
        "rank": rank,
    }

    # ── 3. Price histogram (8 equal-width buckets, category-relative) ─────────
    cat_prices = [r["price"] for r in cat_rows if r["price"] is not None]
    brand_prices = [r["price"] for r in brand_rows if r["price"] is not None]
    cat_min = min(cat_prices) if cat_prices else 0.0
    cat_max = max(cat_prices) if cat_prices else 0.0

    width = (cat_max - cat_min) / 8 if cat_min != cat_max else 1.0
    labels = []
    for i in range(8):
        lo = cat_min + i * width
        hi = cat_min + (i + 1) * width
        labels.append(f"₹{lo:.0f}–{hi:.0f}")

    price_histogram = {
        "labels": labels,
        "brand": _histogram_8(brand_prices, cat_min, cat_max),
        "category": _histogram_8(cat_prices, cat_min, cat_max),
    }

    # ── 4. MRP tiers (category tertiles) ──────────────────────────────────────
    cat_mrps = sorted(r["mrp"] for r in cat_rows if r["mrp"] is not None)
    brand_mrps = [r["mrp"] for r in brand_rows if r["mrp"] is not None]
    budget_threshold = _percentile(cat_mrps, 33.33)
    premium_threshold = _percentile(cat_mrps, 66.67)

    def _tier_counts(mrps: list[float]) -> list[int]:
        budget = sum(1 for m in mrps if m <= budget_threshold)
        mid = sum(1 for m in mrps if budget_threshold < m <= premium_threshold)
        premium = sum(1 for m in mrps if m > premium_threshold)
        return [budget, mid, premium]

    mrp_tiers = {
        "labels": ["Budget", "Mid", "Premium"],
        "brand": _tier_counts(brand_mrps),
        "category": _tier_counts([r["mrp"] for r in cat_rows if r["mrp"] is not None]),
        "budget_threshold": round(budget_threshold, 2),
        "premium_threshold": round(premium_threshold, 2),
    }

    # ── 5. Discount ───────────────────────────────────────────────────────────
    def _avg_discount(rows: list) -> float:
        discounts = []
        for r in rows:
            if r["price"] is not None and r["mrp"] is not None and r["mrp"] > 0:
                d = (r["mrp"] - r["price"]) / r["mrp"] * 100
                if d > 0:
                    discounts.append(d)
        return round(sum(discounts) / len(discounts), 2) if discounts else 0.0

    discount = {
        "brand_avg": _avg_discount(brand_rows),
        "category_avg": _avg_discount(cat_rows),
    }

    # ── 6. Platform coverage ──────────────────────────────────────────────────
    by_platform: dict[str, int] = {}
    for r in brand_rows:
        by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1

    # Cross-platform canonical count: canonicals that have ≥2 mappings for this brand
    xplat_row = conn.execute(
        "SELECT COUNT(DISTINCT pm.canonical_id) as cnt "
        "FROM product_mappings pm "
        "JOIN product_catalog pc ON pm.catalog_id = pc.id "
        "JOIN ("
        "  SELECT canonical_id FROM product_mappings pm2 "
        "  JOIN product_catalog pc2 ON pm2.catalog_id = pc2.id "
        "  WHERE pc2.brand = ? AND pc2.category = ? "
        "  GROUP BY pm2.canonical_id HAVING COUNT(DISTINCT pc2.platform) >= 2"
        ") cp ON pm.canonical_id = cp.canonical_id "
        "WHERE pc.brand = ? AND pc.category = ?",
        [brand, category, brand, category],
    ).fetchone()
    cross_platform_count = xplat_row["cnt"] if xplat_row else 0

    platform_coverage = {
        "by_platform": by_platform,
        "cross_platform_count": cross_platform_count,
        "total": sku_count,
    }

    # ── 7. Price parity (cross-platform canonical pairs with delta) ───────────
    parity_rows = conn.execute(
        "SELECT cp.canonical_name, "
        "  MAX(CASE WHEN pc.platform = 'blinkit' THEN po.price END) AS blinkit_price, "
        "  MAX(CASE WHEN pc.platform = 'zepto'   THEN po.price END) AS zepto_price "
        "FROM canonical_products cp "
        "JOIN product_mappings pm ON pm.canonical_id = cp.id "
        "JOIN product_catalog pc ON pm.catalog_id = pc.id "
        "LEFT JOIN ("
        "  SELECT catalog_id, price FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON po.catalog_id = pc.id "
        "WHERE cp.brand = ? AND cp.category = ? "
        "GROUP BY cp.id, cp.canonical_name "
        "HAVING blinkit_price IS NOT NULL AND zepto_price IS NOT NULL",
        [brand, category],
    ).fetchall()

    price_parity = []
    for r in parity_rows:
        bp = r["blinkit_price"]
        zp = r["zepto_price"]
        delta = round(bp - zp, 2)
        if delta == 0.0:
            continue
        delta_pct = round(abs(delta) / max(bp, zp) * 100, 2)
        price_parity.append({
            "canonical_name": r["canonical_name"],
            "blinkit_price": bp,
            "zepto_price": zp,
            "delta": delta,
            "delta_pct": delta_pct,
        })

    # ── 8. All competitors (every brand in category) ──────────────────────────
    all_competitors = []
    for b, cnt in sorted(brand_counts.items(), key=lambda x: -x[1]):
        all_competitors.append({
            "brand": b,
            "sku_count": cnt,
            "is_target": b == brand,
        })

    # ── 9. Canonical competitors (brands sharing canonical clusters with target) ─
    canon_rows = conn.execute(
        "SELECT DISTINCT pc2.brand "
        "FROM product_mappings pm "
        "JOIN product_catalog pc ON pm.catalog_id = pc.id "
        "JOIN product_mappings pm2 ON pm2.canonical_id = pm.canonical_id "
        "JOIN product_catalog pc2 ON pm2.catalog_id = pc2.id "
        "WHERE pc.brand = ? AND pc.category = ? "
        "  AND pc2.brand != ? AND pc2.brand IS NOT NULL",
        [brand, category, brand],
    ).fetchall()
    canonical_competitors = [{"brand": r["brand"]} for r in canon_rows]

    return ApiResponse(data={
        "share": share,
        "price_histogram": price_histogram,
        "mrp_tiers": mrp_tiers,
        "discount": discount,
        "platform_coverage": platform_coverage,
        "price_parity": price_parity,
        "all_competitors": all_competitors,
        "canonical_competitors": canonical_competitors,
    })
