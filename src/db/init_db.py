"""Database initialization — creates SQLite DB with WAL mode and full schema."""

import logging
import sqlite3
from pathlib import Path

from src.config.settings import settings

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

EXPECTED_TABLES = {
    "product_catalog",
    "product_observations",
    "daily_sales",
    "canonical_products",
    "product_mappings",
    "scrape_runs",
}


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Initialize the SQLite database. Idempotent — safe to call multiple times.

    Returns an open connection with WAL mode enabled.
    """
    db_path = db_path or settings.db_path

    # Ensure data directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={settings.db_busy_timeout}")
    conn.execute("PRAGMA foreign_keys=ON")

    # Run schema
    schema_sql = SCHEMA_PATH.read_text()
    conn.executescript(schema_sql)

    # Verify all tables exist
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    actual_tables = {row[0] for row in cursor.fetchall()}
    missing = EXPECTED_TABLES - actual_tables
    if missing:
        msg = f"Missing tables after init: {missing}"
        raise RuntimeError(msg)

    logger.info("Database initialized at %s with %d tables", db_path, len(actual_tables))
    return conn


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Get a connection to an already-initialized database."""
    db_path = db_path or settings.db_path
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={settings.db_busy_timeout}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn
