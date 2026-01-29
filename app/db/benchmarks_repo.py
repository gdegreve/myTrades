from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.db.connection import get_connection


def list_benchmarks() -> list[dict]:
    """Return all benchmarks ordered by name.

    Returns:
        List of dicts with benchmark metadata including id, code, name, ticker, region, etc.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT
                benchmark_id,
                code,
                name,
                ticker,
                region,
                base_currency,
                description,
                is_active,
                created_at
            FROM benchmarks
            ORDER BY name COLLATE NOCASE
            """
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def add_benchmark(name: str, region: str, ticker: str) -> int:
    """Insert a new benchmark and return its ID.

    Args:
        name: Display name (e.g., "S&P 500")
        region: Geographic region (e.g., "US", "Europe", "Asia")
        ticker: Yahoo Finance ticker symbol (e.g., "^GSPC", "^STOXX")

    Returns:
        benchmark_id of newly created row
    """
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()

        # Generate code from name (uppercase, spaces removed)
        code = name.upper().replace(" ", "").replace("&", "")

        cur.execute(
            """
            INSERT INTO benchmarks (code, name, ticker, region, base_currency, is_active)
            VALUES (?, ?, ?, ?, 'EUR', 1)
            """,
            (code, name, ticker, region),
        )

        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_benchmark(benchmark_id: int, name: str, region: str, ticker: str) -> None:
    """Update an existing benchmark's metadata.

    Args:
        benchmark_id: ID of benchmark to update
        name: New display name
        region: New region
        ticker: New ticker symbol
    """
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        # Generate code from name (uppercase, spaces removed)
        code = name.upper().replace(" ", "").replace("&", "")

        conn.execute(
            """
            UPDATE benchmarks
            SET code = ?,
                name = ?,
                ticker = ?,
                region = ?
            WHERE benchmark_id = ?
            """,
            (code, name, ticker, region, benchmark_id),
        )

        conn.commit()
    finally:
        conn.close()


def delete_benchmark(benchmark_id: int) -> None:
    """Delete a benchmark (CASCADE will delete benchmark_eod rows).

    Args:
        benchmark_id: ID of benchmark to delete
    """
    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            "DELETE FROM benchmarks WHERE benchmark_id = ?",
            (benchmark_id,),
        )

        conn.commit()
    finally:
        conn.close()


def get_benchmark_eod(benchmark_id: int, start_date: str, end_date: str) -> list[dict]:
    """Get cached EOD price data for a benchmark within date range.

    Args:
        benchmark_id: Benchmark ID
        start_date: ISO date string (YYYY-MM-DD)
        end_date: ISO date string (YYYY-MM-DD)

    Returns:
        List of dicts with keys: date, close
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT date, close
            FROM benchmark_eod
            WHERE benchmark_id = ?
              AND date >= ?
              AND date <= ?
            ORDER BY date
            """,
            (benchmark_id, start_date, end_date),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def upsert_benchmark_eod(benchmark_id: int, bars: list[dict]) -> None:
    """Batch insert/update EOD price bars for a benchmark.

    Args:
        benchmark_id: Benchmark ID
        bars: List of dicts with keys: date (str), close (float)

    Example:
        bars = [
            {"date": "2024-01-01", "close": 4769.83},
            {"date": "2024-01-02", "close": 4783.45}
        ]
    """
    if not bars:
        return

    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.cursor()

        for bar in bars:
            cur.execute(
                """
                INSERT INTO benchmark_eod (benchmark_id, date, close)
                VALUES (?, ?, ?)
                ON CONFLICT(benchmark_id, date)
                DO UPDATE SET close = excluded.close
                """,
                (benchmark_id, bar["date"], bar["close"]),
            )

        conn.commit()
    finally:
        conn.close()


def ensure_benchmark_eod_cached(
    benchmark_id: int, ticker: str, start_date: str, end_date: str
) -> None:
    """Ensure EOD data is cached for the given date range, fetching missing dates from yfinance.

    Args:
        benchmark_id: Benchmark ID
        ticker: Yahoo Finance ticker (e.g., "^GSPC")
        start_date: ISO date string (YYYY-MM-DD)
        end_date: ISO date string (YYYY-MM-DD)

    Raises:
        ImportError: If yfinance is not installed
        Exception: If ticker not found or network error
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError as e:
        raise ImportError("yfinance is required for price fetching. Install with: pip install yfinance") from e

    conn = get_connection()
    try:
        # Get existing dates in cache
        cur = conn.execute(
            """
            SELECT date
            FROM benchmark_eod
            WHERE benchmark_id = ?
              AND date >= ?
              AND date <= ?
            """,
            (benchmark_id, start_date, end_date),
        )
        cached_dates = {row["date"] for row in cur.fetchall()}

        # Generate all business days in range
        date_range = pd.date_range(start=start_date, end=end_date, freq="D")
        all_dates = {d.strftime("%Y-%m-%d") for d in date_range}

        # Identify missing dates
        missing_dates = all_dates - cached_dates

        if not missing_dates:
            return  # All dates cached

        # Fetch from yfinance (will only return market days)
        try:
            data = yf.download(ticker, start=start_date, end=end_date, progress=False)

            if data.empty:
                raise ValueError(f"No data returned for ticker {ticker}")

            # Prepare bars for insertion
            bars = []
            for date_idx, row in data.iterrows():
                date_str = date_idx.strftime("%Y-%m-%d")
                # Handle both single-ticker and multi-ticker DataFrame formats
                if isinstance(row["Close"], pd.Series):
                    close_price = float(row["Close"].iloc[0])
                else:
                    close_price = float(row["Close"])
                bars.append({"date": date_str, "close": close_price})

            # Upsert fetched data
            if bars:
                upsert_benchmark_eod(benchmark_id, bars)

        except Exception as e:
            raise Exception(f"Failed to fetch data for {ticker}: {str(e)}") from e

    finally:
        conn.close()


def get_latest_snapshot_all_benchmarks() -> list[dict]:
    """Get latest close price and previous close for all active benchmarks (for P/L %).

    Returns:
        List of dicts with keys:
        - benchmark_id
        - name
        - ticker
        - latest_date
        - latest_close
        - prev_date
        - prev_close
        - change_pct (calculated)
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            WITH latest AS (
                SELECT
                    e.benchmark_id,
                    MAX(e.date) AS latest_date
                FROM benchmark_eod e
                JOIN benchmarks b ON b.benchmark_id = e.benchmark_id
                WHERE b.is_active = 1
                GROUP BY e.benchmark_id
            ),
            latest_with_close AS (
                SELECT
                    l.benchmark_id,
                    l.latest_date,
                    e.close AS latest_close
                FROM latest l
                JOIN benchmark_eod e ON e.benchmark_id = l.benchmark_id AND e.date = l.latest_date
            ),
            prev AS (
                SELECT
                    e.benchmark_id,
                    MAX(e.date) AS prev_date
                FROM benchmark_eod e
                JOIN latest l ON l.benchmark_id = e.benchmark_id
                WHERE e.date < l.latest_date
                GROUP BY e.benchmark_id
            ),
            prev_with_close AS (
                SELECT
                    p.benchmark_id,
                    p.prev_date,
                    e.close AS prev_close
                FROM prev p
                JOIN benchmark_eod e ON e.benchmark_id = p.benchmark_id AND e.date = p.prev_date
            )
            SELECT
                b.benchmark_id,
                b.name,
                b.ticker,
                b.region,
                lw.latest_date,
                lw.latest_close,
                pw.prev_date,
                pw.prev_close,
                CASE
                    WHEN pw.prev_close IS NOT NULL AND pw.prev_close != 0
                    THEN ((lw.latest_close - pw.prev_close) / pw.prev_close) * 100.0
                    ELSE NULL
                END AS change_pct
            FROM benchmarks b
            JOIN latest_with_close lw ON lw.benchmark_id = b.benchmark_id
            LEFT JOIN prev_with_close pw ON pw.benchmark_id = b.benchmark_id
            WHERE b.is_active = 1
            ORDER BY b.name COLLATE NOCASE
            """
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
