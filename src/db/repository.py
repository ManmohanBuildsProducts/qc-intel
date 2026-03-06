"""Repository pattern for all database operations. All DB access goes through here."""

import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

from src.models.product import (
    CanonicalProduct,
    CatalogProduct,
    Confidence,
    Platform,
    ProductMapping,
    ProductObservation,
    SalesEstimate,
    ScrapeRun,
    ScrapeRunStatus,
    TimeOfDay,
)

logger = logging.getLogger(__name__)


@contextmanager
def get_cursor(conn: sqlite3.Connection) -> Generator[sqlite3.Cursor, None, None]:
    """Context manager for cursor with auto-commit/rollback."""
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class CatalogRepository:
    """CRUD for product_catalog table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_product(self, product: CatalogProduct) -> int:
        """Insert or update a catalog product. Returns the product id."""
        with get_cursor(self.conn) as cur:
            cur.execute(
                """
                INSERT INTO product_catalog
                    (platform, platform_product_id, name, brand, category, subcategory, unit, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, platform_product_id) DO UPDATE SET
                    name = excluded.name,
                    brand = excluded.brand,
                    category = excluded.category,
                    subcategory = excluded.subcategory,
                    unit = excluded.unit,
                    image_url = excluded.image_url,
                    last_seen_at = datetime('now')
                """,
                (
                    product.platform.value,
                    product.platform_product_id,
                    product.name,
                    product.brand,
                    product.category,
                    product.subcategory,
                    product.unit,
                    product.image_url,
                ),
            )
            # Get the id (works for both insert and update)
            cur.execute(
                "SELECT id FROM product_catalog WHERE platform = ? AND platform_product_id = ?",
                (product.platform.value, product.platform_product_id),
            )
            return cur.fetchone()[0]

    def get_by_id(self, product_id: int) -> CatalogProduct | None:
        """Get a catalog product by id."""
        row = self.conn.execute(
            "SELECT * FROM product_catalog WHERE id = ?", (product_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_model(row)

    def get_by_platform(self, platform: Platform) -> list[CatalogProduct]:
        """Get all catalog products for a platform."""
        rows = self.conn.execute(
            "SELECT * FROM product_catalog WHERE platform = ?", (platform.value,)
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_by_category(self, category: str) -> list[CatalogProduct]:
        """Get all catalog products in a category."""
        rows = self.conn.execute(
            "SELECT * FROM product_catalog WHERE category = ?", (category,)
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_by_brand(self, brand: str) -> list[CatalogProduct]:
        """Get all catalog products for a brand."""
        rows = self.conn.execute(
            "SELECT * FROM product_catalog WHERE brand = ?", (brand,)
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_all_for_normalization(self) -> list[CatalogProduct]:
        """Get all catalog products that need normalization."""
        rows = self.conn.execute(
            """
            SELECT pc.* FROM product_catalog pc
            LEFT JOIN product_mappings pm ON pc.id = pm.catalog_id
            WHERE pm.catalog_id IS NULL
            """
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def _row_to_model(self, row: sqlite3.Row) -> CatalogProduct:
        return CatalogProduct(
            id=row[0],
            platform=Platform(row[1]),
            platform_product_id=row[2],
            name=row[3],
            brand=row[4],
            category=row[5],
            subcategory=row[6],
            unit=row[7],
            image_url=row[8],
            first_seen_at=datetime.fromisoformat(row[9]) if row[9] else None,
            last_seen_at=datetime.fromisoformat(row[10]) if row[10] else None,
        )


class ObservationRepository:
    """CRUD for product_observations table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_observation(self, obs: ProductObservation) -> int:
        """Insert a new observation. Returns the observation id."""
        with get_cursor(self.conn) as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO product_observations
                    (catalog_id, scrape_run_id, pincode, price, mrp, in_stock, max_cart_qty, time_of_day, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs.catalog_id,
                    obs.scrape_run_id,
                    obs.pincode,
                    obs.price,
                    obs.mrp,
                    1 if obs.in_stock else 0,
                    obs.max_cart_qty,
                    obs.time_of_day.value,
                    obs.raw_json,
                ),
            )
            return cur.lastrowid

    def get_by_date_and_time(
        self, date: str, time_of_day: TimeOfDay, pincode: str | None = None
    ) -> list[ProductObservation]:
        """Get observations for a given date and time of day."""
        query = """
            SELECT * FROM product_observations
            WHERE date(observed_at) = ? AND time_of_day = ?
        """
        params: list = [date, time_of_day.value]
        if pincode:
            query += " AND pincode = ?"
            params.append(pincode)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_latest_for_product(self, catalog_id: int, pincode: str) -> ProductObservation | None:
        """Get the most recent observation for a product at a pincode."""
        row = self.conn.execute(
            "SELECT * FROM product_observations WHERE catalog_id = ? AND pincode = ? ORDER BY observed_at DESC LIMIT 1",
            (catalog_id, pincode),
        ).fetchone()
        if not row:
            return None
        return self._row_to_model(row)

    def _row_to_model(self, row: sqlite3.Row) -> ProductObservation:
        return ProductObservation(
            id=row[0],
            catalog_id=row[1],
            scrape_run_id=row[2],
            pincode=row[3],
            price=row[4],
            mrp=row[5],
            in_stock=bool(row[6]),
            max_cart_qty=row[7],
            time_of_day=TimeOfDay(row[8]),
            observed_at=datetime.fromisoformat(row[9]) if row[9] else None,
            raw_json=row[10],
        )


class SalesRepository:
    """CRUD for daily_sales table + sales calculation logic."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def calculate_and_store_daily_sales(self, date: str, pincode: str | None = None) -> int:
        """Calculate daily sales from morning/night observation pairs.

        Returns the number of sales records created.
        """
        # Get morning observations
        morning_query = """
            SELECT catalog_id, max_cart_qty FROM product_observations
            WHERE date(observed_at) = ? AND time_of_day = 'morning'
        """
        night_query = """
            SELECT catalog_id, pincode, max_cart_qty FROM product_observations
            WHERE date(observed_at) = ? AND time_of_day = 'night'
        """
        params: list = [date]
        if pincode:
            morning_query += " AND pincode = ?"
            night_query += " AND pincode = ?"
            params.append(pincode)

        self.conn.execute(morning_query, params).fetchall()
        night_rows = self.conn.execute(night_query, params).fetchall()

        # Build lookup: (catalog_id, pincode) -> morning_qty
        # For morning, we also need pincode
        morning_full = self.conn.execute(
            """
            SELECT catalog_id, pincode, max_cart_qty FROM product_observations
            WHERE date(observed_at) = ? AND time_of_day = 'morning'
            """
            + (" AND pincode = ?" if pincode else ""),
            params,
        ).fetchall()

        morning_map: dict[tuple[int, str], int] = {}
        for row in morning_full:
            morning_map[(row[0], row[1])] = row[2]

        count = 0
        with get_cursor(self.conn) as cur:
            for row in night_rows:
                cat_id, pin, night_qty = row[0], row[1], row[2]
                key = (cat_id, pin)

                if key not in morning_map:
                    # Missing morning → no_data
                    continue

                morning_qty = morning_map[key]
                del morning_map[key]  # Mark as processed

                # Calculate
                if morning_qty > night_qty:
                    estimated = morning_qty - night_qty
                    confidence = Confidence.HIGH
                    restock = False
                elif morning_qty == night_qty:
                    estimated = 0
                    confidence = Confidence.MEDIUM
                    restock = False
                else:
                    # night > morning = restock
                    estimated = 0
                    confidence = Confidence.LOW
                    restock = True

                cur.execute(
                    """
                    INSERT OR REPLACE INTO daily_sales (
                        catalog_id, pincode, sale_date, morning_qty,
                        night_qty, estimated_sales, confidence, restock_flag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cat_id, pin, date, morning_qty, night_qty, estimated, confidence.value, 1 if restock else 0),
                )
                count += 1

        return count

    def get_sales_by_category(self, category: str, date: str | None = None) -> list[SalesEstimate]:
        """Get sales estimates for a category, optionally filtered by date."""
        query = """
            SELECT ds.* FROM daily_sales ds
            JOIN product_catalog pc ON ds.catalog_id = pc.id
            WHERE pc.category = ?
        """
        params: list = [category]
        if date:
            query += " AND ds.sale_date = ?"
            params.append(date)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_top_sellers(self, limit: int = 20, date: str | None = None) -> list[SalesEstimate]:
        """Get top selling products by estimated sales."""
        query = "SELECT * FROM daily_sales WHERE confidence = 'high'"
        params: list = []
        if date:
            query += " AND sale_date = ?"
            params.append(date)
        query += " ORDER BY estimated_sales DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_model(r) for r in rows]

    def _row_to_model(self, row: sqlite3.Row) -> SalesEstimate:
        return SalesEstimate(
            id=row[0],
            catalog_id=row[1],
            pincode=row[2],
            sale_date=row[3],
            morning_qty=row[4],
            night_qty=row[5],
            estimated_sales=row[6],
            confidence=Confidence(row[7]),
            restock_flag=bool(row[8]),
        )


class CanonicalRepository:
    """CRUD for canonical_products and product_mappings tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_canonical(self, product: CanonicalProduct) -> int:
        """Insert a canonical product. Returns the id."""
        with get_cursor(self.conn) as cur:
            cur.execute(
                """
                INSERT INTO canonical_products (canonical_name, brand, category, unit_normalized, embedding)
                VALUES (?, ?, ?, ?, ?)
                """,
                (product.canonical_name, product.brand, product.category, product.unit_normalized, product.embedding),
            )
            return cur.lastrowid

    def insert_mapping(self, mapping: ProductMapping) -> None:
        """Insert a product mapping (catalog → canonical)."""
        with get_cursor(self.conn) as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO product_mappings (catalog_id, canonical_id, similarity_score)
                VALUES (?, ?, ?)
                """,
                (mapping.catalog_id, mapping.canonical_id, mapping.similarity_score),
            )

    def get_unmapped(self) -> list[CatalogProduct]:
        """Get catalog products not yet mapped to a canonical product."""
        rows = self.conn.execute(
            """
            SELECT pc.* FROM product_catalog pc
            LEFT JOIN product_mappings pm ON pc.id = pm.catalog_id
            WHERE pm.catalog_id IS NULL
            """
        ).fetchall()
        return [
            CatalogProduct(
                id=r[0],
                platform=Platform(r[1]),
                platform_product_id=r[2],
                name=r[3],
                brand=r[4],
                category=r[5],
                subcategory=r[6],
                unit=r[7],
                image_url=r[8],
            )
            for r in rows
        ]

    def get_cross_platform_view(self) -> list[dict]:
        """Get canonical products with their platform mappings."""
        rows = self.conn.execute(
            """
            SELECT cp.id, cp.canonical_name, cp.brand, cp.category, cp.unit_normalized,
                   pc.platform, pc.name, pc.platform_product_id, pm.similarity_score
            FROM canonical_products cp
            JOIN product_mappings pm ON cp.id = pm.canonical_id
            JOIN product_catalog pc ON pm.catalog_id = pc.id
            ORDER BY cp.id, pc.platform
            """
        ).fetchall()

        result: dict[int, dict] = {}
        for r in rows:
            cid = r[0]
            if cid not in result:
                result[cid] = {
                    "canonical_id": cid,
                    "canonical_name": r[1],
                    "brand": r[2],
                    "category": r[3],
                    "unit": r[4],
                    "platforms": [],
                }
            result[cid]["platforms"].append({
                "platform": r[5],
                "name": r[6],
                "product_id": r[7],
                "similarity": r[8],
            })

        return list(result.values())


class ScrapeRunRepository:
    """CRUD for scrape_runs table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_run(self, run: ScrapeRun) -> str:
        """Create a new scrape run record. Returns the run id."""
        with get_cursor(self.conn) as cur:
            cur.execute(
                """
                INSERT INTO scrape_runs (id, platform, pincode, category, time_of_day, started_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.platform.value,
                    run.pincode,
                    run.category,
                    run.time_of_day.value,
                    run.started_at.isoformat() if run.started_at else datetime.now().isoformat(),
                    run.status.value,
                ),
            )
            return run.id

    def complete_run(self, run_id: str, products_found: int, errors: int = 0) -> None:
        """Mark a run as completed."""
        with get_cursor(self.conn) as cur:
            cur.execute(
                """
                UPDATE scrape_runs SET status = 'completed', completed_at = datetime('now'),
                    products_found = ?, errors = ?
                WHERE id = ?
                """,
                (products_found, errors, run_id),
            )

    def fail_run(self, run_id: str, errors: int = 1) -> None:
        """Mark a run as failed."""
        with get_cursor(self.conn) as cur:
            cur.execute(
                """
                UPDATE scrape_runs SET status = 'failed', completed_at = datetime('now'), errors = ?
                WHERE id = ?
                """,
                (errors, run_id),
            )

    def get_runs_by_date(self, date: str) -> list[ScrapeRun]:
        """Get all scrape runs for a date."""
        rows = self.conn.execute(
            "SELECT * FROM scrape_runs WHERE date(started_at) = ?", (date,)
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def _row_to_model(self, row: sqlite3.Row) -> ScrapeRun:
        return ScrapeRun(
            id=row[0],
            platform=Platform(row[1]),
            pincode=row[2],
            category=row[3],
            time_of_day=TimeOfDay(row[4]),
            started_at=datetime.fromisoformat(row[5]) if row[5] else None,
            completed_at=datetime.fromisoformat(row[6]) if row[6] else None,
            products_found=row[7] or 0,
            errors=row[8] or 0,
            status=ScrapeRunStatus(row[9]),
        )
