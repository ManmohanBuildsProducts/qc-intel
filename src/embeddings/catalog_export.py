"""Export product catalog data to JSON for Kaggle embedding upload."""

import json
import logging
import sqlite3
from pathlib import Path

from src.embeddings.unit_normalizer import normalize_unit

logger = logging.getLogger(__name__)

ANCHOR_PLATFORM_PREFERENCE = ["blinkit", "zepto", "instamart"]


def _compose_text(name: str, brand: str | None, unit: str | None) -> str:
    """Compose embedding text from product fields: '{brand} {name} {unit}'."""
    parts: list[str] = []
    if brand:
        parts.append(brand)
    parts.append(name)
    if unit:
        normalized = normalize_unit(unit)
        if normalized:
            parts.append(normalized)
    return " ".join(parts)


def export_catalog_for_embedding(
    conn: sqlite3.Connection,
    category: str | None = None,
) -> list[dict]:
    """Query product_catalog and return list of dicts with embedding-ready fields.

    Args:
        conn: SQLite connection with row_factory = sqlite3.Row.
        category: Optional category filter.

    Returns:
        List of dicts with: id, name, brand, category, subcategory, unit,
        platform, platform_product_id, text.
    """
    query = """
        SELECT id, name, brand, category, subcategory, unit, platform, platform_product_id
        FROM product_catalog
    """
    params: list[str] = []
    if category:
        query += " WHERE category = ?"
        params.append(category)
    query += " ORDER BY id"

    old_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.row_factory = old_factory

    products: list[dict] = []
    for row in rows:
        product = {
            "id": row["id"],
            "name": row["name"],
            "brand": row["brand"],
            "category": row["category"],
            "subcategory": row["subcategory"],
            "unit": row["unit"],
            "platform": row["platform"],
            "platform_product_id": row["platform_product_id"],
            "text": _compose_text(row["name"], row["brand"], row["unit"]),
        }
        products.append(product)

    logger.info("Exported %d catalog products%s", len(products), f" for category={category}" if category else "")
    return products


def export_catalog_to_json(
    conn: sqlite3.Connection,
    output_path: str,
    category: str | None = None,
) -> str:
    """Export catalog to JSON grouped by platform with anchor selection.

    Args:
        conn: SQLite connection.
        output_path: Path to write the JSON file.
        category: Optional category filter.

    Returns:
        The output path written.
    """
    products = export_catalog_for_embedding(conn, category=category)

    # Group by platform
    by_platform: dict[str, list[dict]] = {}
    for p in products:
        by_platform.setdefault(p["platform"], []).append(p)

    # Select anchor platform (blinkit preferred)
    anchor_platform = None
    for pref in ANCHOR_PLATFORM_PREFERENCE:
        if pref in by_platform:
            anchor_platform = pref
            break

    if anchor_platform is None and by_platform:
        anchor_platform = next(iter(by_platform))

    anchor_products = by_platform.pop(anchor_platform, [])

    output = {
        "category": category,
        "anchor_platform": anchor_platform,
        "anchor_products": anchor_products,
        "other_products": by_platform,
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    logger.info("Wrote catalog export to %s (%d anchor, %d other platforms)",
                output_path, len(anchor_products), len(by_platform))
    return str(path)


def export_fixtures_to_json(output_path: str) -> str:
    """Load test fixtures into in-memory DB and export as JSON.

    Used for benchmark evaluation on Kaggle.

    Args:
        output_path: Path to write the JSON file.

    Returns:
        The output path written.
    """
    from src.agents.scraper.service import ScrapeService
    from src.db.init_db import init_db
    from src.models.product import Platform, TimeOfDay

    fixtures_dir = Path(__file__).parent.parent.parent / "tests" / "fixtures"

    conn = init_db(":memory:")
    conn.row_factory = sqlite3.Row
    service = ScrapeService(conn)

    platform_fixtures = [
        (Platform.BLINKIT, "blinkit_dairy.json"),
        (Platform.ZEPTO, "zepto_dairy.json"),
        (Platform.INSTAMART, "instamart_dairy.json"),
    ]

    for platform, fixture_file in platform_fixtures:
        data = json.loads((fixtures_dir / fixture_file).read_text())
        service.process_scrape_results(data, platform, "122001", "Dairy & Bread", TimeOfDay.MORNING)

    result = export_catalog_to_json(conn, output_path, category="Dairy & Bread")
    conn.close()
    return result
