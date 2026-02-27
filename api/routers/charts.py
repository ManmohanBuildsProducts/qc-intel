"""Chart endpoints — price distribution, platform coverage, brand share."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from api.deps import get_db
from api.models import ApiResponse, ChartDataset, ChartResponse

router = APIRouter(prefix="/charts")

PLATFORM_COLORS = {
    "blinkit": "#F8CB46",
    "zepto": "#7B2FBF",
    "instamart": "#FC8019",
}


@router.get("/price-distribution")
def price_distribution(
    category: str = Query(...),
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    rows = conn.execute(
        "SELECT pc.platform, po.price "
        "FROM product_catalog pc "
        "JOIN ("
        "  SELECT catalog_id, price "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        ") po ON pc.id = po.catalog_id "
        "WHERE pc.category = ?",
        [category],
    ).fetchall()

    buckets = ["₹0-50", "₹50-100", "₹100-200", "₹200-500", "₹500+"]
    platforms = sorted({row["platform"] for row in rows})

    def bucket_index(price: float) -> int:
        if price < 50:
            return 0
        if price < 100:
            return 1
        if price < 200:
            return 2
        if price < 500:
            return 3
        return 4

    datasets: list[ChartDataset] = []
    for platform in platforms:
        counts = [0] * len(buckets)
        for row in rows:
            if row["platform"] == platform:
                counts[bucket_index(row["price"])] += 1
        datasets.append(
            ChartDataset(
                label=platform,
                data=counts,
                backgroundColor=PLATFORM_COLORS.get(platform),
            )
        )

    chart = ChartResponse(labels=buckets, datasets=datasets)
    return ApiResponse(data=chart.model_dump())


@router.get("/platform-coverage")
def platform_coverage(
    brand: str = Query(...),
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    rows = conn.execute(
        "SELECT platform, COUNT(*) as cnt "
        "FROM product_catalog WHERE brand = ? GROUP BY platform",
        [brand],
    ).fetchall()

    labels = [row["platform"] for row in rows]
    data = [row["cnt"] for row in rows]
    colors = [PLATFORM_COLORS.get(label, "#999999") for label in labels]

    chart = ChartResponse(
        labels=labels,
        datasets=[ChartDataset(label="Products", data=data, backgroundColor=colors)],
    )
    return ApiResponse(data=chart.model_dump())


@router.get("/brand-share")
def brand_share(
    category: str = Query(...),
    conn: sqlite3.Connection = Depends(get_db),
) -> ApiResponse:
    rows = conn.execute(
        "SELECT brand, COUNT(*) as cnt "
        "FROM product_catalog WHERE category = ? AND brand IS NOT NULL "
        "GROUP BY brand ORDER BY cnt DESC",
        [category],
    ).fetchall()

    top_10 = rows[:10]
    others_count = sum(row["cnt"] for row in rows[10:])

    labels = [row["brand"] for row in top_10]
    data: list[int] = [row["cnt"] for row in top_10]
    if others_count > 0:
        labels.append("Others")
        data.append(others_count)

    chart = ChartResponse(
        labels=labels,
        datasets=[ChartDataset(label="Products", data=data)],
    )
    return ApiResponse(data=chart.model_dump())
