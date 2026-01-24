from __future__ import annotations

import sqlite3
from pathlib import Path


def get_db_path() -> Path:
    # Single source of truth for the Dash project
    return Path("data/trading.sqlite")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with Row factory enabled."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
