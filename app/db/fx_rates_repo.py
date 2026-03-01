"""FX rates repository for currency conversion.

Provides read and write operations for foreign exchange rates
used in multi-currency portfolio calculations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.connection import get_connection


def get_latest_fx_rate(base: str, quote: str) -> float | None:
    """Get most recent FX rate for currency pair.

    Args:
        base: Base currency code (e.g., "EUR")
        quote: Quote currency code (e.g., "USD")

    Returns:
        Exchange rate (float) or None if not found.
        Example: base='EUR', quote='USD', rate=1.08 means 1 EUR = 1.08 USD

    Note:
        If requesting inverse pair (USD->EUR but only EUR->USD exists),
        caller should invert the rate (1/rate).
    """
    if not base or not quote:
        return None

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT rate
            FROM fx_rates
            WHERE base_currency = ? AND quote_currency = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (base.upper(), quote.upper()),
        ).fetchone()

        return row["rate"] if row else None


def get_fx_rate_on_date(base: str, quote: str, date: str) -> float | None:
    """Get FX rate for currency pair on specific date.

    Args:
        base: Base currency code (e.g., "EUR")
        quote: Quote currency code (e.g., "USD")
        date: ISO date string (YYYY-MM-DD)

    Returns:
        Exchange rate (float) or None if not found.
        Falls back to most recent rate before the requested date.

    Usage:
        For historical trade conversions where FX rate at trade time is needed.
    """
    if not base or not quote or not date:
        return None

    with get_connection() as conn:
        # Try exact date first
        row = conn.execute(
            """
            SELECT rate
            FROM fx_rates
            WHERE base_currency = ? AND quote_currency = ? AND date = ?
            """,
            (base.upper(), quote.upper(), date),
        ).fetchone()

        if row:
            return row["rate"]

        # Fallback: most recent rate before requested date
        row = conn.execute(
            """
            SELECT rate
            FROM fx_rates
            WHERE base_currency = ? AND quote_currency = ? AND date <= ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (base.upper(), quote.upper(), date),
        ).fetchone()

        return row["rate"] if row else None


def upsert_fx_rates(rates: list[dict[str, Any]]) -> None:
    """Insert or update FX rates in database (transactional).

    Args:
        rates: List of rate dicts with keys:
            - base_currency: str (e.g., "EUR")
            - quote_currency: str (e.g., "USD")
            - rate: float (exchange rate)
            - date: str (ISO date YYYY-MM-DD)
            - provider: str (default "yfinance")

    Behavior:
        - Uses INSERT OR REPLACE for idempotent upserts
        - Sets fetched_at to current UTC timestamp
        - Transactional: all or nothing

    Example:
        rates = [
            {"base_currency": "EUR", "quote_currency": "USD",
             "rate": 1.08, "date": "2026-02-11"},
        ]
        upsert_fx_rates(rates)

    Raises:
        sqlite3.Error on database failure
    """
    if not rates:
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_connection() as conn:
        cur = conn.cursor()
        for rate_data in rates:
            cur.execute(
                """
                INSERT OR REPLACE INTO fx_rates (
                    base_currency, quote_currency, rate, date, fetched_at, provider
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    rate_data["base_currency"].upper(),
                    rate_data["quote_currency"].upper(),
                    rate_data["rate"],
                    rate_data["date"],
                    now,
                    rate_data.get("provider", "yfinance"),
                ),
            )
        conn.commit()


def get_all_fx_rates(base: str | None = None, quote: str | None = None) -> list[dict[str, Any]]:
    """Get all FX rates, optionally filtered by base or quote currency.

    Args:
        base: Optional base currency filter
        quote: Optional quote currency filter

    Returns:
        List of dicts with keys: base_currency, quote_currency, rate, date, fetched_at

    Usage:
        Debugging and inspection. Most code should use get_latest_fx_rate() instead.
    """
    with get_connection() as conn:
        if base and quote:
            query = """
                SELECT base_currency, quote_currency, rate, date, fetched_at
                FROM fx_rates
                WHERE base_currency = ? AND quote_currency = ?
                ORDER BY date DESC
            """
            params = (base.upper(), quote.upper())
        elif base:
            query = """
                SELECT base_currency, quote_currency, rate, date, fetched_at
                FROM fx_rates
                WHERE base_currency = ?
                ORDER BY date DESC
            """
            params = (base.upper(),)
        elif quote:
            query = """
                SELECT base_currency, quote_currency, rate, date, fetched_at
                FROM fx_rates
                WHERE quote_currency = ?
                ORDER BY date DESC
            """
            params = (quote.upper(),)
        else:
            query = """
                SELECT base_currency, quote_currency, rate, date, fetched_at
                FROM fx_rates
                ORDER BY date DESC
            """
            params = ()

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
