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


def upsert_benchmark_tickers(benchmark_id: int, tickers: list[str]) -> int:
    """Append tickers to benchmark_tickers table (no deletion of existing).

    Args:
        benchmark_id: Benchmark ID
        tickers: List of ticker symbols

    Returns:
        Number of tickers added (excluding duplicates)
    """
    if not tickers:
        return 0

    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        added = 0
        for ticker in tickers:
            try:
                conn.execute(
                    """
                    INSERT INTO benchmark_tickers (benchmark_id, ticker, weight)
                    VALUES (?, ?, NULL)
                    """,
                    (benchmark_id, ticker),
                )
                added += 1
            except Exception:
                pass
        conn.commit()
        return added
    finally:
        conn.close()


def get_benchmark_tickers_with_fundamentals(benchmark_id: int) -> list[dict]:
    """Get tickers for a benchmark with latest fundamental snapshot data.

    Returns:
        List of dicts with keys: ticker, sector, fundamental_label,
        bench_score_total, bench_sector_pct_total, bench_confidence, updated_at
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT
                bt.ticker,
                bf.sector,
                bf.fundamental_label,
                bf.bench_score_total,
                bf.bench_sector_pct_total,
                bf.bench_confidence,
                bf.updated_at
            FROM benchmark_tickers bt
            LEFT JOIN (
                SELECT
                    benchmark_id,
                    ticker,
                    sector,
                    fundamental_label,
                    bench_score_total,
                    bench_sector_pct_total,
                    bench_confidence,
                    updated_at,
                    ROW_NUMBER() OVER (PARTITION BY benchmark_id, ticker ORDER BY updated_at DESC) as rn
                FROM benchmark_fundamentals
                WHERE status = 'ok'
            ) bf ON bf.benchmark_id = bt.benchmark_id AND bf.ticker = bt.ticker AND bf.rn = 1
            WHERE bt.benchmark_id = ?
            ORDER BY bt.ticker
            """,
            (benchmark_id,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def refresh_benchmark_fundamentals(benchmark_id: int, tickers: list[str]) -> dict:
    """Refresh fundamental snapshot data for specific tickers.

    Args:
        benchmark_id: Benchmark ID
        tickers: List of ticker symbols to refresh

    Returns:
        Dict with keys: succeeded (int), failed (int), run_id (str)
    """
    import yfinance as yf
    from datetime import datetime, timezone

    if not tickers:
        return {"succeeded": 0, "failed": 0, "run_id": ""}

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    succeeded = 0
    failed = 0

    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        for ticker in tickers:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info

                if not info or "symbol" not in info:
                    failed += 1
                    continue

                sector = info.get("sector")
                roe = info.get("returnOnEquity")
                operating_margins = info.get("operatingMargins")
                pe_ttm = info.get("trailingPE")
                forward_pe = info.get("forwardPE")
                peg = info.get("pegRatio")
                ev_to_ebitda = info.get("enterpriseToEbitda")
                price_to_book = info.get("priceToBook")
                price_to_sales = info.get("priceToSalesTrailing12Months")

                quality_score = 0.0
                if roe and roe > 0.15:
                    quality_score += 50
                if operating_margins and operating_margins > 0.20:
                    quality_score += 50

                safety_score = 0.0
                if ev_to_ebitda and ev_to_ebitda < 10:
                    safety_score += 50
                if price_to_book and price_to_book < 3:
                    safety_score += 50

                value_score = 0.0
                if pe_ttm and pe_ttm < 20:
                    value_score += 30
                if forward_pe and forward_pe < 18:
                    value_score += 30
                if peg and peg < 1.5:
                    value_score += 40

                total_score = (quality_score + safety_score + value_score) / 3.0

                # Compute data completeness confidence (0-100%)
                fields_to_check = [sector, roe, operating_margins, pe_ttm, forward_pe, peg, ev_to_ebitda, price_to_book, price_to_sales]
                if sector is None:
                    bench_confidence = 0.0
                else:
                    non_null_count = sum(1 for f in fields_to_check if f is not None)
                    total_fields = len(fields_to_check)
                    bench_confidence = round(100 * non_null_count / total_fields, 1)

                # Determine label
                if total_score >= 70:
                    label = "INTERESTING"
                elif total_score >= 50:
                    label = "EXPENSIVE"
                elif total_score >= 30:
                    label = "DOUBTFUL"
                else:
                    label = "AVOID"

                conn.execute(
                    """
                    INSERT INTO benchmark_fundamentals
                    (run_id, benchmark_id, ticker, sector,
                     bench_score_total, bench_score_quality, bench_score_safety, bench_score_value,
                     bench_confidence, fundamental_label,
                     roe, operating_margins, pe_ttm, forward_pe, peg,
                     ev_to_ebitda, price_to_book, price_to_sales,
                     status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', ?)
                    """,
                    (
                        run_id,
                        benchmark_id,
                        ticker,
                        sector,
                        total_score,
                        quality_score,
                        safety_score,
                        value_score,
                        bench_confidence,
                        label,
                        roe,
                        operating_margins,
                        pe_ttm,
                        forward_pe,
                        peg,
                        ev_to_ebitda,
                        price_to_book,
                        price_to_sales,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )

                if sector:
                    conn.execute(
                        """
                        INSERT INTO ticker_sectors (ticker, sector)
                        VALUES (?, ?)
                        ON CONFLICT(ticker) DO UPDATE SET sector = excluded.sector
                        """,
                        (ticker, sector),
                    )

                succeeded += 1
            except Exception:
                failed += 1

        conn.commit()
        return {"succeeded": succeeded, "failed": failed, "run_id": run_id}
    finally:
        conn.close()


def get_benchmark_snapshot_tickers(benchmark_id: int) -> list[dict]:
    """Get latest snapshot data for all tickers in a benchmark.

    Returns:
        List of dicts with snapshot essentials for Analysis → Fundamental Finder
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT
                bf.ticker,
                COALESCE(bf.ticker_name, bf.company_name) as ticker_name,
                bf.sector,
                bf.fundamental_label,
                bf.bench_score_total,
                bf.bench_score_quality,
                bf.bench_score_safety,
                bf.bench_score_value,
                bf.bench_sector_pct_total,
                bf.bench_confidence,
                bf.updated_at
            FROM benchmark_tickers bt
            LEFT JOIN (
                SELECT
                    benchmark_id,
                    ticker,
                    sector,
                    fundamental_label,
                    bench_score_total,
                    bench_score_quality,
                    bench_score_safety,
                    bench_score_value,
                    bench_sector_pct_total,
                    bench_confidence,
                    updated_at,
                    NULL as ticker_name,
                    NULL as company_name,
                    ROW_NUMBER() OVER (PARTITION BY benchmark_id, ticker ORDER BY updated_at DESC) as rn
                FROM benchmark_fundamentals
                WHERE status = 'ok'
            ) bf ON bf.benchmark_id = bt.benchmark_id AND bf.ticker = bt.ticker AND bf.rn = 1
            WHERE bt.benchmark_id = ?
            ORDER BY bt.ticker
            """,
            (benchmark_id,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_ticker_snapshot_detail(benchmark_id: int, ticker: str) -> dict | None:
    """Get detailed snapshot data for a specific ticker.

    Returns:
        Dict with all stored fundamental fields, or None if not found
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT
                ticker,
                sector,
                fundamental_label,
                bench_score_total,
                bench_score_quality,
                bench_score_safety,
                bench_score_value,
                bench_sector_pct_total,
                bench_sector_n,
                bench_confidence,
                roe,
                operating_margins,
                pe_ttm,
                forward_pe,
                peg,
                ev_to_ebitda,
                price_to_book,
                price_to_sales,
                updated_at
            FROM benchmark_fundamentals
            WHERE benchmark_id = ? AND ticker = ? AND status = 'ok'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (benchmark_id, ticker),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
