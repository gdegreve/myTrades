"""Ticker region metadata repository.

Read and write operations for ticker→region mapping.
Supports batch queries and transactional upserts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.connection import get_connection


def get_ticker_regions(tickers: list[str] | None = None) -> dict[str, str]:
    """Retrieve region mapping for given tickers.

    Args:
        tickers: List of ticker symbols (e.g., ["AAPL", "ASML.AS"]).
                 If None, returns all mappings.

    Returns:
        Dict mapping ticker -> region (e.g., {"AAPL": "North America"}).
        Missing tickers are excluded from result.

    Query:
        Read-only query against ticker_regions table.
    """
    with get_connection() as con:
        if tickers is None:
            query = "SELECT ticker, region FROM ticker_regions"
            cur = con.execute(query)
        else:
            if not tickers:
                return {}
            placeholders = ",".join("?" for _ in tickers)
            query = f"SELECT ticker, region FROM ticker_regions WHERE ticker IN ({placeholders})"
            cur = con.execute(query, tickers)

        rows = cur.fetchall()

    return {row["ticker"]: row["region"] for row in rows}


def upsert_ticker_regions(mapping: dict[str, str]) -> None:
    """Insert or update ticker→region mappings (transactional).

    Args:
        mapping: Dict of ticker -> region (e.g., {"AAPL": "North America"}).

    Behavior:
        - Uses INSERT OR REPLACE for idempotent upserts
        - Sets updated_at to current UTC timestamp
        - Transactional: all or nothing

    Raises:
        sqlite3.Error on database failure
    """
    if not mapping:
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection() as con:
        cur = con.cursor()
        for ticker, region in mapping.items():
            cur.execute(
                """
                INSERT OR REPLACE INTO ticker_regions (ticker, region, updated_at)
                VALUES (?, ?, ?)
                """,
                (ticker, region, now),
            )
        con.commit()


def list_distinct_regions() -> list[str]:
    """List all distinct region values currently in the mapping table.

    Returns:
        Sorted list of unique region names.

    Query:
        Read-only aggregation query.
    """
    with get_connection() as con:
        cur = con.execute("SELECT DISTINCT region FROM ticker_regions ORDER BY region")
        rows = cur.fetchall()

    return [row["region"] for row in rows]
