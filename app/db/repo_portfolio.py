from __future__ import annotations

from app.db.sqlite import connect, table_exists, fetch_all


def list_portfolios() -> list[dict]:
    """
    Read-only portfolio list.

    Expected table (for now):
      portfolios(id INTEGER, name TEXT, created_at TEXT, ...)

    If the table doesn't exist yet, returns an empty list.
    """
    conn = connect()
    try:
        if not table_exists(conn, "portfolios"):
            return []
    finally:
        conn.close()

    # Query columns defensively: try to fetch common fields; SQLite will error if missing.
    # So we keep it minimal: id + name.
    return fetch_all(
        "SELECT id, name FROM portfolios ORDER BY name COLLATE NOCASE",
    )

def list_holdings(portfolio_id: int) -> list[dict]:
    """
    Read-only holdings for a portfolio. Joins sector info if available.
    """
    conn = connect()
    try:
        if not table_exists(conn, "holdings"):
            return []
        # ticker_sectors is optional; if missing, we still return holdings
        has_sectors = table_exists(conn, "ticker_sectors")
    finally:
        conn.close()

    if has_sectors:
        return fetch_all(
            """
            SELECT
                h.ticker,
                h.total_shares,
                h.avg_cost,
                COALESCE(ts.sector, '') AS sector,
                h.last_updated
            FROM holdings h
            LEFT JOIN ticker_sectors ts ON ts.ticker = h.ticker
            WHERE h.portfolio_id = ?
            ORDER BY h.ticker COLLATE NOCASE
            """,
            (portfolio_id,),
        )

    return fetch_all(
        """
        SELECT
            ticker,
            total_shares,
            avg_cost,
            '' AS sector,
            last_updated
        FROM holdings
        WHERE portfolio_id = ?
        ORDER BY ticker COLLATE NOCASE
        """,
        (portfolio_id,),
    )
