"""Price data repository for SQLite cache.

Read-only and write operations for daily close prices.
Supports batch queries and transactional upserts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.connection import get_connection


def get_latest_daily_closes(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Retrieve latest daily close prices for given tickers from cache.

    Args:
        tickers: List of ticker symbols (e.g., ["AAPL", "MSFT"])

    Returns:
        Dict mapping ticker -> {
            "close": float,
            "date": str (ISO date),
            "currency": str,
            "fetched_at": str (ISO timestamp)
        }
        Missing tickers are excluded from result.

    Query:
        For each ticker, get the most recent date's close price
        where interval='1d'.
    """
    if not tickers:
        return {}

    with get_connection() as con:
        # Build query to get latest date per ticker
        placeholders = ",".join("?" for _ in tickers)
        query = f"""
            SELECT
                symbol,
                date,
                close,
                currency,
                fetched_at
            FROM price_bars
            WHERE symbol IN ({placeholders})
              AND interval = '1d'
              AND (symbol, date) IN (
                  SELECT symbol, MAX(date)
                  FROM price_bars
                  WHERE symbol IN ({placeholders})
                    AND interval = '1d'
                  GROUP BY symbol
              )
        """
        cur = con.execute(query, tickers + tickers)
        rows = cur.fetchall()

    result = {}
    for row in rows:
        result[row["symbol"]] = {
            "close": row["close"],
            "date": row["date"],
            "currency": row["currency"],
            "fetched_at": row["fetched_at"],
        }

    return result


def upsert_daily_closes(bars: list[dict[str, Any]]) -> None:
    """Insert or update daily close prices in cache (transactional).

    Args:
        bars: List of price bar dicts with keys:
            - symbol: str (ticker)
            - date: str (ISO date YYYY-MM-DD)
            - close: float
            - currency: str (default 'EUR')
            - provider: str (default 'yfinance')

    Behavior:
        - Uses INSERT OR REPLACE for idempotent upserts
        - Sets fetched_at to current UTC timestamp
        - Transactional: all or nothing

    Raises:
        sqlite3.Error on database failure
    """
    if not bars:
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection() as con:
        cur = con.cursor()
        for bar in bars:
            cur.execute(
                """
                INSERT OR REPLACE INTO price_bars (
                    symbol, interval, date, close, currency, provider, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bar["symbol"],
                    "1d",  # Locked to daily interval
                    bar["date"],
                    bar["close"],
                    bar.get("currency", "EUR"),
                    bar.get("provider", "yfinance"),
                    now,
                ),
            )
        con.commit()
