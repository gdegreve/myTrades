from __future__ import annotations

from typing import Any

from app.db.connection import get_connection


def list_portfolios() -> list[dict[str, Any]]:
    """Return portfolios for dropdowns/navigation."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT id, name
            FROM portfolios
            ORDER BY name COLLATE NOCASE
            """
        )
        return [dict(r) for r in cur.fetchall()]
