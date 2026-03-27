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


@router.get("/brand/{brand}/scorecard")
def brand_scorecard(
    brand: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    """Brand overview across ALL categories — the single-screen answer."""
    # All SKUs for this brand with latest observations
    rows = conn.execute(
        "SELECT pc.id, pc.platform, pc.category, po.price, po.mrp "
        "FROM product_catalog pc "
        "LEFT JOIN ("
        "  SELECT catalog_id, price, mrp "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON pc.id = po.catalog_id "
        "WHERE pc.brand = ?",
        [brand],
    ).fetchall()

    total_skus = len(rows)
    categories = sorted(set(r["category"] for r in rows if r["category"]))
    platforms = sorted(set(r["platform"] for r in rows if r["platform"]))

    # Platform SKU counts
    platform_skus: dict[str, int] = {}
    for r in rows:
        platform_skus[r["platform"]] = platform_skus.get(r["platform"], 0) + 1
    # Ensure all 3 platforms appear
    for p in ("blinkit", "zepto", "instamart"):
        platform_skus.setdefault(p, 0)

    # Avg discount
    discounts = []
    for r in rows:
        if r["price"] is not None and r["mrp"] is not None and r["mrp"] > 0:
            d = (r["mrp"] - r["price"]) / r["mrp"] * 100
            if d > 0:
                discounts.append(d)
    avg_discount = round(sum(discounts) / len(discounts), 1) if discounts else 0.0

    # Price range
    prices = [r["price"] for r in rows if r["price"] is not None]
    price_range = {
        "min": min(prices) if prices else 0,
        "max": max(prices) if prices else 0,
    }

    # Per-category breakdown
    cat_details = []
    for cat in categories:
        # All SKUs in this category (all brands)
        cat_all = conn.execute(
            "SELECT pc.id, pc.brand, pc.platform, po.price, po.mrp "
            "FROM product_catalog pc "
            "LEFT JOIN ("
            "  SELECT catalog_id, price, mrp "
            "  FROM product_observations "
            "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
            ") po ON pc.id = po.catalog_id "
            "WHERE pc.category = ?",
            [cat],
        ).fetchall()

        cat_total = len(cat_all)
        brand_cat_rows = [r for r in cat_all if r["brand"] == brand]
        brand_sku_count = len(brand_cat_rows)
        share_pct = round(brand_sku_count / cat_total * 100, 1) if cat_total else 0.0

        # Rank
        cat_brand_counts: dict[str, int] = {}
        for r in cat_all:
            if r["brand"]:
                cat_brand_counts[r["brand"]] = cat_brand_counts.get(r["brand"], 0) + 1
        my_count = cat_brand_counts.get(brand, 0)
        cat_rank = sum(1 for c in cat_brand_counts.values() if c > my_count) + 1

        # Platforms
        brand_platforms = sorted(set(r["platform"] for r in brand_cat_rows))
        all_platforms = {"blinkit", "zepto", "instamart"}
        missing = sorted(all_platforms - set(brand_platforms))

        # Avg prices
        brand_prices = [r["price"] for r in brand_cat_rows if r["price"] is not None]
        cat_prices = [r["price"] for r in cat_all if r["price"] is not None]
        avg_price = round(sum(brand_prices) / len(brand_prices), 1) if brand_prices else 0.0
        cat_avg_price = round(sum(cat_prices) / len(cat_prices), 1) if cat_prices else 0.0

        # Avg discount
        brand_disc = []
        cat_disc = []
        for r in brand_cat_rows:
            if r["price"] and r["mrp"] and r["mrp"] > 0:
                d = (r["mrp"] - r["price"]) / r["mrp"] * 100
                if d > 0:
                    brand_disc.append(d)
        for r in cat_all:
            if r["price"] and r["mrp"] and r["mrp"] > 0:
                d = (r["mrp"] - r["price"]) / r["mrp"] * 100
                if d > 0:
                    cat_disc.append(d)

        cat_details.append({
            "category": cat,
            "sku_count": brand_sku_count,
            "category_total": cat_total,
            "share_pct": share_pct,
            "rank": cat_rank,
            "total_brands": len(cat_brand_counts),
            "platforms": brand_platforms,
            "missing_platforms": missing,
            "avg_price": avg_price,
            "category_avg_price": cat_avg_price,
            "avg_discount_pct": round(sum(brand_disc) / len(brand_disc), 1) if brand_disc else 0.0,
            "category_avg_discount_pct": round(sum(cat_disc) / len(cat_disc), 1) if cat_disc else 0.0,
        })

    return ApiResponse(data={
        "brand": brand,
        "total_skus": total_skus,
        "category_count": len(categories),
        "platform_count": len(platforms),
        "platform_skus": platform_skus,
        "avg_discount_pct": avg_discount,
        "price_range": price_range,
        "categories": cat_details,
    })


@router.get("/brand/{brand}/gaps")
def brand_gaps(
    brand: str,
    category: str = Query(...),
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    """Distribution gaps — which platforms carry each product."""
    all_platforms = ["blinkit", "zepto", "instamart"]

    # Get brand products in category with latest prices
    rows = conn.execute(
        "SELECT pc.id, pc.platform, pc.name, po.price "
        "FROM product_catalog pc "
        "LEFT JOIN ("
        "  SELECT catalog_id, price "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON pc.id = po.catalog_id "
        "WHERE pc.brand = ? AND pc.category = ?",
        [brand, category],
    ).fetchall()

    # Try canonical matching first
    canonical_rows = conn.execute(
        "SELECT cp.id AS canonical_id, cp.canonical_name, "
        "  pc.platform, po.price "
        "FROM canonical_products cp "
        "JOIN product_mappings pm ON pm.canonical_id = cp.id "
        "JOIN product_catalog pc ON pm.catalog_id = pc.id "
        "LEFT JOIN ("
        "  SELECT catalog_id, price "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON po.catalog_id = pc.id "
        "WHERE cp.brand = ? AND cp.category = ?",
        [brand, category],
    ).fetchall()

    # Build platform matrix from canonical products
    canonical_map: dict[str, dict] = {}
    matched_catalog_ids: set[int] = set()

    for r in canonical_rows:
        cname = r["canonical_name"]
        if cname not in canonical_map:
            canonical_map[cname] = {"product_name": cname}
            for p in all_platforms:
                canonical_map[cname][p] = {"present": False, "price": None}
        plat = r["platform"]
        canonical_map[cname][plat] = {"present": True, "price": r["price"]}

    # Add unmatched (single-platform) products
    # Get catalog IDs that ARE mapped
    if canonical_rows:
        mapped_ids_rows = conn.execute(
            "SELECT pm.catalog_id "
            "FROM product_mappings pm "
            "JOIN product_catalog pc ON pm.catalog_id = pc.id "
            "WHERE pc.brand = ? AND pc.category = ?",
            [brand, category],
        ).fetchall()
        matched_catalog_ids = {r["catalog_id"] for r in mapped_ids_rows}

    for r in rows:
        if r["id"] not in matched_catalog_ids:
            name = r["name"]
            entry: dict = {"product_name": name}
            for p in all_platforms:
                entry[p] = {"present": False, "price": None}
            entry[r["platform"]] = {"present": True, "price": r["price"]}
            canonical_map[name] = entry

    # Build matrix and summary
    matrix = list(canonical_map.values())
    for item in matrix:
        item["gap_count"] = sum(1 for p in all_platforms if not item[p]["present"])

    # Sort: most gaps first
    matrix.sort(key=lambda x: -x["gap_count"])

    on_all = sum(1 for m in matrix if m["gap_count"] == 0)
    on_two = sum(1 for m in matrix if m["gap_count"] == 1)
    on_one = sum(1 for m in matrix if m["gap_count"] == 2)

    platform_gaps: dict[str, int] = {}
    for p in all_platforms:
        platform_gaps[p] = sum(1 for m in matrix if not m[p]["present"])

    return ApiResponse(data={
        "brand": brand,
        "category": category,
        "platform_matrix": matrix,
        "summary": {
            "total_products": len(matrix),
            "on_all": on_all,
            "on_two": on_two,
            "on_one": on_one,
            "platform_gaps": platform_gaps,
        },
    })


@router.get("/brand/{brand}/discount-battle")
def discount_battle(
    brand: str,
    category: str = Query(...),
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    """Discount intensity ranking — are competitors discounting more aggressively?"""
    rows = conn.execute(
        "SELECT pc.brand, po.price, po.mrp "
        "FROM product_catalog pc "
        "LEFT JOIN ("
        "  SELECT catalog_id, price, mrp "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON pc.id = po.catalog_id "
        "WHERE pc.category = ?",
        [category],
    ).fetchall()

    # Group by brand
    brand_data: dict[str, list[dict]] = {}
    for r in rows:
        b = r["brand"]
        if b:
            brand_data.setdefault(b, []).append(r)

    brands_result = []
    all_discounts = []
    for b, b_rows in brand_data.items():
        discounts = []
        discounted_count = 0
        for r in b_rows:
            if r["price"] is not None and r["mrp"] is not None and r["mrp"] > 0:
                d = (r["mrp"] - r["price"]) / r["mrp"] * 100
                if d > 0:
                    discounts.append(d)
                    discounted_count += 1
                    all_discounts.append(d)
        avg_disc = round(sum(discounts) / len(discounts), 1) if discounts else 0.0
        disc_pct = round(discounted_count / len(b_rows) * 100, 1) if b_rows else 0.0
        brands_result.append({
            "brand": b,
            "is_target": b == brand,
            "avg_discount_pct": avg_disc,
            "discounted_sku_pct": disc_pct,
            "sku_count": len(b_rows),
        })

    # Sort by avg discount descending
    brands_result.sort(key=lambda x: -x["avg_discount_pct"])

    cat_avg = round(sum(all_discounts) / len(all_discounts), 1) if all_discounts else 0.0

    return ApiResponse(data={
        "brands": brands_result,
        "category_avg_discount": cat_avg,
    })
