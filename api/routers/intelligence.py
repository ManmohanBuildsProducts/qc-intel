"""Category intelligence endpoints — landscape and whitespace analysis."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from api.deps import get_db
from api.models import ApiResponse

router = APIRouter()


@router.get("/category/{category}/landscape")
def category_landscape(
    category: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    """Bubble chart data — brand positioning in a category."""
    rows = conn.execute(
        "SELECT pc.brand, pc.platform, po.price, po.mrp "
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
        if r["brand"]:
            brand_data.setdefault(r["brand"], []).append(r)

    brands = []
    all_prices = [r["price"] for r in rows if r["price"] is not None]

    for b, b_rows in brand_data.items():
        prices = [r["price"] for r in b_rows if r["price"] is not None]
        avg_price = round(sum(prices) / len(prices), 1) if prices else 0.0

        discounts = []
        for r in b_rows:
            if r["price"] is not None and r["mrp"] is not None and r["mrp"] > 0:
                d = (r["mrp"] - r["price"]) / r["mrp"] * 100
                if d > 0:
                    discounts.append(d)
        avg_discount = round(sum(discounts) / len(discounts), 1) if discounts else 0.0

        platforms = sorted(set(r["platform"] for r in b_rows))

        brands.append({
            "brand": b,
            "sku_count": len(b_rows),
            "avg_price": avg_price,
            "avg_discount_pct": avg_discount,
            "platforms": platforms,
            "platform_count": len(platforms),
        })

    brands.sort(key=lambda x: -x["sku_count"])

    return ApiResponse(data={
        "category": category,
        "total_brands": len(brands),
        "total_skus": len(rows),
        "brands": brands,
        "price_range": {
            "min": min(all_prices) if all_prices else 0,
            "max": max(all_prices) if all_prices else 0,
        },
    })


@router.get("/category/{category}/whitespace")
def category_whitespace(
    category: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    """Price gap analysis — under-served price bands as opportunities."""
    rows = conn.execute(
        "SELECT pc.brand, po.price "
        "FROM product_catalog pc "
        "LEFT JOIN ("
        "  SELECT catalog_id, price "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON pc.id = po.catalog_id "
        "WHERE pc.category = ? AND po.price IS NOT NULL",
        [category],
    ).fetchall()

    if not rows:
        return ApiResponse(data={
            "price_bands": [],
            "total_skus": 0,
            "total_brands": 0,
        })

    prices = [r["price"] for r in rows]
    min_price = min(prices)
    max_price = max(prices)
    all_brands = set(r["brand"] for r in rows if r["brand"])

    # 10 equal-width bands
    num_bands = 10
    width = (max_price - min_price) / num_bands if max_price > min_price else 1.0

    bands = []
    for i in range(num_bands):
        lo = min_price + i * width
        hi = min_price + (i + 1) * width

        band_rows = [
            r for r in rows
            if (lo <= r["price"] < hi) or (i == num_bands - 1 and r["price"] == hi)
        ]
        band_brands = set(r["brand"] for r in band_rows if r["brand"])
        # Top brands by SKU count in this band
        brand_counts: dict[str, int] = {}
        for r in band_rows:
            if r["brand"]:
                brand_counts[r["brand"]] = brand_counts.get(r["brand"], 0) + 1
        top = sorted(brand_counts.items(), key=lambda x: -x[1])[:3]

        density = "sparse" if len(band_brands) <= 3 else ("moderate" if len(band_brands) <= 8 else "crowded")

        bands.append({
            "range": f"\u20b9{lo:.0f}-{hi:.0f}",
            "sku_count": len(band_rows),
            "brand_count": len(band_brands),
            "top_brands": [b for b, _ in top],
            "density": density,
        })

    return ApiResponse(data={
        "price_bands": bands,
        "total_skus": len(rows),
        "total_brands": len(all_brands),
    })
