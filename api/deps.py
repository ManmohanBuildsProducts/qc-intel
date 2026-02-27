"""FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator

from src.db.init_db import get_connection


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a database connection, closing it after the request."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
