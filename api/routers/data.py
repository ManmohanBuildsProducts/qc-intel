"""Data endpoints — brands, categories, products, dashboard stats."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from api.deps import get_db
from api.models import (
    ApiResponse,
    BrandItem,
    CategoryItem,
    DashboardStats,
    PaginatedResponse,
    ProductItem,
)

router = APIRouter()


@router.get("/brands")
def list_brands(conn: sqlite3.Connection = Depends(get_db)) -> ApiResponse:
    rows = conn.execute(
        "SELECT brand, COUNT(*) as cnt, GROUP_CONCAT(DISTINCT category) as cats "
        "FROM product_catalog WHERE brand IS NOT NULL "
        "GROUP BY brand ORDER BY cnt DESC"
    ).fetchall()
    items = [
        BrandItem(
            name=row["brand"],
            product_count=row["cnt"],
            categories=row["cats"].split(",") if row["cats"] else [],
        )
        for row in rows
    ]
    return ApiResponse(data=[item.model_dump() for item in items])


@router.get("/categories")
def list_categories(conn: sqlite3.Connection = Depends(get_db)) -> ApiResponse:
    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt, COUNT(DISTINCT brand) as brand_cnt "
        "FROM product_catalog GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    items = [
        CategoryItem(
            name=row["category"],
            product_count=row["cnt"],
            brand_count=row["brand_cnt"],
        )
        for row in rows
    ]
    return ApiResponse(data=[item.model_dump() for item in items])


@router.get("/products")
def list_products(
    brand: str | None = Query(None),
    category: str | None = Query(None),
    platform: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
) -> PaginatedResponse:
    conditions: list[str] = []
    params: list[str] = []
    if brand:
        conditions.append("pc.brand = ?")
        params.append(brand)
    if category:
        conditions.append("pc.category = ?")
        params.append(category)
    if platform:
        conditions.append("pc.platform = ?")
        params.append(platform)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Count query
    count_row = conn.execute(
        f"SELECT COUNT(*) as total FROM product_catalog pc {where}", params  # noqa: S608
    ).fetchone()
    total = count_row["total"]

    offset = (page - 1) * per_page
    rows = conn.execute(
        "SELECT pc.id, pc.platform, pc.name, pc.brand, pc.category, pc.unit, "
        "po.price, po.mrp, po.in_stock "
        "FROM product_catalog pc "
        "LEFT JOIN ("
        "  SELECT catalog_id, price, mrp, in_stock "
        "  FROM product_observations "
        "  WHERE id IN (SELECT MAX(id) FROM product_observations GROUP BY catalog_id)"
        f") po ON pc.id = po.catalog_id {where} "  # noqa: S608
        "ORDER BY pc.id "
        "LIMIT ? OFFSET ?",
        [*params, per_page, offset],
    ).fetchall()

    items = [
        ProductItem(
            id=row["id"],
            platform=row["platform"],
            name=row["name"],
            brand=row["brand"],
            category=row["category"],
            unit=row["unit"],
            price=row["price"],
            mrp=row["mrp"],
            in_stock=bool(row["in_stock"]) if row["in_stock"] is not None else None,
        ).model_dump()
        for row in rows
    ]
    return PaginatedResponse(
        data=items,
        meta={"total": total, "page": page, "per_page": per_page},
    )


@router.get("/dashboard/stats")
def dashboard_stats(conn: sqlite3.Connection = Depends(get_db)) -> ApiResponse:
    row = conn.execute(
        "SELECT "
        "  COUNT(*) as products, "
        "  COUNT(DISTINCT brand) as brands, "
        "  COUNT(DISTINCT category) as categories, "
        "  COUNT(DISTINCT platform) as platforms "
        "FROM product_catalog"
    ).fetchone()

    scrape_row = conn.execute(
        "SELECT started_at FROM scrape_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    last_scrape = scrape_row["started_at"] if scrape_row else None

    stats = DashboardStats(
        products=row["products"],
        brands=row["brands"],
        categories=row["categories"],
        platforms=row["platforms"],
        last_scrape=last_scrape,
    )
    return ApiResponse(data=stats.model_dump())
