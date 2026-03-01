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


def get_active_portfolio_ids(exclude_watchlist: bool = True) -> list[int]:
    """Get list of active portfolio IDs.

    Args:
        exclude_watchlist: If True, exclude portfolios named "Watchlist" (case-insensitive)

    Returns:
        List of portfolio IDs
    """
    with get_connection() as conn:
        if exclude_watchlist:
            cur = conn.execute(
                """
                SELECT id
                FROM portfolios
                WHERE LOWER(name) != 'watchlist'
                ORDER BY id ASC
                """
            )
        else:
            cur = conn.execute(
                """
                SELECT id
                FROM portfolios
                ORDER BY id ASC
                """
            )
        return [row["id"] for row in cur.fetchall()]
