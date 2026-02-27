"""Sales estimation service — wraps SalesRepository with orchestration logic."""

import logging
import sqlite3

from src.db.repository import CatalogRepository, SalesRepository

logger = logging.getLogger(__name__)


class SalesService:
    """Orchestrates sales calculation and summary generation."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.sales_repo = SalesRepository(conn)
        self.catalog_repo = CatalogRepository(conn)

    def calculate_daily_sales(self, date: str, pincode: str | None = None) -> dict:
        """Run sales calculation for a date. Returns summary stats."""
        count = self.sales_repo.calculate_and_store_daily_sales(date, pincode)

        # Query results for summary
        query = "SELECT confidence, COUNT(*) as cnt FROM daily_sales WHERE sale_date = ?"
        params: list = [date]
        if pincode:
            query += " AND pincode = ?"
            params.append(pincode)
        query += " GROUP BY confidence"

        rows = self.conn.execute(query, params).fetchall()
        by_confidence = {row[0]: row[1] for row in rows}

        total_sales = self.conn.execute(
            "SELECT COALESCE(SUM(estimated_sales), 0) FROM daily_sales WHERE sale_date = ?"
            + (" AND pincode = ?" if pincode else ""),
            params,
        ).fetchone()[0]

        return {
            "date": date,
            "pincode": pincode,
            "records_created": count,
            "total_estimated_sales": total_sales,
            "by_confidence": by_confidence,
        }

    def get_category_sales_summary(self, category: str, date: str) -> list[dict]:
        """Get sales summary grouped by brand for a category."""
        rows = self.conn.execute(
            """
            SELECT pc.brand, COUNT(*) as product_count,
                   SUM(ds.estimated_sales) as total_sales,
                   AVG(CASE WHEN ds.confidence = 'high' THEN 1.0
                            WHEN ds.confidence = 'medium' THEN 0.5
                            WHEN ds.confidence = 'low' THEN 0.25
                            ELSE 0.0 END) as avg_confidence
            FROM daily_sales ds
            JOIN product_catalog pc ON ds.catalog_id = pc.id
            WHERE pc.category = ? AND ds.sale_date = ?
            GROUP BY pc.brand
            ORDER BY total_sales DESC
            """,
            (category, date),
        ).fetchall()

        return [
            {
                "brand": row[0],
                "product_count": row[1],
                "total_estimated_sales": row[2],
                "avg_confidence": round(row[3], 2),
            }
            for row in rows
        ]
