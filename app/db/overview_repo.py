"""Repository functions for Portfolio Overview page.

SQL-first approach for performance-critical metrics:
- Daily portfolio values for time series charts
- Benchmark comparison data
- Daily P/L contributors
- Sector allocation
"""
from __future__ import annotations

from typing import Any

from app.db.connection import get_connection


def get_portfolio_summary(portfolio_id: int) -> dict[str, Any]:
    """Get portfolio summary data in a single optimized query.

    Returns:
        dict with keys: cash_balance, benchmark_ticker, total_invested
    """
    with get_connection() as conn:
        # Compute cash balance from cash_transactions ledger
        cur = conn.execute(
            """
            SELECT COALESCE(
                SUM(CASE WHEN cash_type = 'credit' THEN amount_eur ELSE -amount_eur END),
                0
            ) as cash_balance
            FROM cash_transactions
            WHERE portfolio_id = ?
            """,
            (portfolio_id,),
        )
        row = cur.fetchone()
        cash_balance = row["cash_balance"] if row else 0.0

        # Get benchmark ticker from policy
        cur = conn.execute(
            "SELECT benchmark_ticker FROM portfolio_policy WHERE portfolio_id = ?",
            (portfolio_id,),
        )
        row = cur.fetchone()
        benchmark_ticker = row["benchmark_ticker"] if row else None

        # Get total invested (sum of buy trades - sum of sell trades in cost)
        cur = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type = 'buy' THEN shares * price_eur ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN transaction_type = 'sell' THEN shares * price_eur ELSE 0 END), 0) as total_invested
            FROM transactions
            WHERE portfolio_id = ?
            """,
            (portfolio_id,),
        )
        row = cur.fetchone()
        total_invested = row["total_invested"] if row else 0.0

        return {
            "cash_balance": cash_balance,
            "benchmark_ticker": benchmark_ticker,
            "total_invested": total_invested,
        }


def get_current_positions(portfolio_id: int) -> list[dict[str, Any]]:
    """Get current positions with aggregated shares and cost basis.

    Returns list of dicts with: ticker, shares, avg_cost, cost_basis
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                ticker,
                SUM(CASE WHEN transaction_type = 'buy' THEN shares ELSE -shares END) as shares,
                SUM(CASE WHEN transaction_type = 'buy' THEN shares * price_eur ELSE 0 END) as total_buy_cost,
                SUM(CASE WHEN transaction_type = 'buy' THEN shares ELSE 0 END) as total_buy_shares
            FROM transactions
            WHERE portfolio_id = ?
            GROUP BY ticker
            HAVING shares > 0.0001
            """,
            (portfolio_id,),
        )
        rows = cur.fetchall()

        positions = []
        for row in rows:
            shares = row["shares"]
            total_buy_cost = row["total_buy_cost"] or 0.0
            total_buy_shares = row["total_buy_shares"] or 0.0
            avg_cost = total_buy_cost / total_buy_shares if total_buy_shares > 0 else 0.0
            cost_basis = shares * avg_cost

            positions.append({
                "ticker": row["ticker"],
                "shares": shares,
                "avg_cost": avg_cost,
                "cost_basis": cost_basis,
            })

        return positions


def get_price_history(symbols: list[str], limit: int = 365) -> dict[str, list[dict]]:
    """Get historical price data for given symbols.

    Returns dict of {symbol: [{date, close}, ...]} sorted by date ascending.
    """
    if not symbols:
        return {}

    with get_connection() as conn:
        placeholders = ",".join("?" for _ in symbols)
        cur = conn.execute(
            f"""
            SELECT symbol, date, close
            FROM price_bars
            WHERE symbol IN ({placeholders})
              AND interval = '1d'
            ORDER BY symbol, date ASC
            LIMIT ?
            """,
            (*symbols, limit * len(symbols)),
        )
        rows = cur.fetchall()

        result: dict[str, list[dict]] = {s: [] for s in symbols}
        for row in rows:
            result[row["symbol"]].append({
                "date": row["date"],
                "close": row["close"],
            })

        return result


def get_latest_prices(symbols: list[str]) -> dict[str, float]:
    """Get latest prices for given symbols from price_bars.

    Returns dict of {symbol: price}.
    """
    if not symbols:
        return {}

    with get_connection() as conn:
        placeholders = ",".join("?" for _ in symbols)
        cur = conn.execute(
            f"""
            SELECT symbol, close
            FROM price_bars
            WHERE (symbol, date) IN (
                SELECT symbol, MAX(date)
                FROM price_bars
                WHERE symbol IN ({placeholders})
                  AND interval = '1d'
                GROUP BY symbol
            )
            """,
            symbols,
        )
        return {row["symbol"]: row["close"] for row in cur.fetchall()}


def get_previous_prices(symbols: list[str]) -> dict[str, float]:
    """Get second-to-latest prices for daily change calculation.

    Returns dict of {symbol: price}.
    """
    if not symbols:
        return {}

    with get_connection() as conn:
        # Get previous day prices using row_number window function
        placeholders = ",".join("?" for _ in symbols)
        cur = conn.execute(
            f"""
            WITH ranked AS (
                SELECT symbol, close, date,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                FROM price_bars
                WHERE symbol IN ({placeholders})
                  AND interval = '1d'
            )
            SELECT symbol, close
            FROM ranked
            WHERE rn = 2
            """,
            symbols,
        )
        return {row["symbol"]: row["close"] for row in cur.fetchall()}


def get_sector_allocations(portfolio_id: int, position_values: dict[str, float]) -> list[dict[str, Any]]:
    """Get sector allocations for current positions.

    Args:
        portfolio_id: Portfolio ID
        position_values: Dict of {ticker: market_value}

    Returns:
        List of dicts with: sector, value, percentage
    """
    if not position_values:
        return []

    total_value = sum(position_values.values())
    if total_value == 0:
        return []

    with get_connection() as conn:
        tickers = list(position_values.keys())
        placeholders = ",".join("?" for _ in tickers)
        cur = conn.execute(
            f"""
            SELECT ticker, sector
            FROM ticker_sectors
            WHERE ticker IN ({placeholders})
            """,
            tickers,
        )
        ticker_to_sector = {row["ticker"]: row["sector"] for row in cur.fetchall()}

    # Aggregate by sector
    sector_values: dict[str, float] = {}
    for ticker, value in position_values.items():
        sector = ticker_to_sector.get(ticker, "Other")
        sector_values[sector] = sector_values.get(sector, 0.0) + value

    # Sort by value descending, keep top 8 + Other
    sorted_sectors = sorted(sector_values.items(), key=lambda x: x[1], reverse=True)

    result = []
    other_value = 0.0

    for i, (sector, value) in enumerate(sorted_sectors):
        if i < 8 and sector != "Other":
            result.append({
                "sector": sector,
                "value": value,
                "percentage": (value / total_value) * 100,
            })
        else:
            other_value += value

    if other_value > 0:
        result.append({
            "sector": "Other",
            "value": other_value,
            "percentage": (other_value / total_value) * 100,
        })

    return result


def get_latest_eod_date() -> str | None:
    """Get the most recent date with price data."""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT MAX(date) as latest FROM price_bars WHERE interval = '1d'"
        )
        row = cur.fetchone()
        return row["latest"] if row else None


def get_price_data_coverage() -> int:
    """Get number of unique dates with price data (for data quality check)."""
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT COUNT(DISTINCT date) as count FROM price_bars WHERE interval = '1d'"
        )
        row = cur.fetchone()
        return row["count"] if row else 0


def get_all_portfolios_summary() -> dict[str, Any]:
    """Get aggregated summary data across ALL portfolios.

    Returns:
        dict with keys: total_cash_balance, total_invested
    """
    with get_connection() as conn:
        # Compute total cash balance from cash_transactions ledger
        cur = conn.execute(
            """
            SELECT COALESCE(
                SUM(CASE WHEN cash_type = 'credit' THEN amount_eur ELSE -amount_eur END),
                0
            ) as total_cash
            FROM cash_transactions
            """
        )
        row = cur.fetchone()
        total_cash_balance = row["total_cash"] if row else 0.0

        # Get total invested across all portfolios
        cur = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN transaction_type = 'buy' THEN shares * price_eur ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN transaction_type = 'sell' THEN shares * price_eur ELSE 0 END), 0) as total_invested
            FROM transactions
            """
        )
        row = cur.fetchone()
        total_invested = row["total_invested"] if row else 0.0

        return {
            "total_cash_balance": total_cash_balance,
            "total_invested": total_invested,
        }


def get_all_current_positions() -> list[dict[str, Any]]:
    """Get current positions aggregated across ALL portfolios.

    Returns list of dicts with: portfolio_id, ticker, shares, avg_cost, cost_basis
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                portfolio_id,
                ticker,
                SUM(CASE WHEN transaction_type = 'buy' THEN shares ELSE -shares END) as shares,
                SUM(CASE WHEN transaction_type = 'buy' THEN shares * price_eur ELSE 0 END) as total_buy_cost,
                SUM(CASE WHEN transaction_type = 'buy' THEN shares ELSE 0 END) as total_buy_shares
            FROM transactions
            GROUP BY portfolio_id, ticker
            HAVING shares > 0.0001
            """
        )
        rows = cur.fetchall()

        positions = []
        for row in rows:
            shares = row["shares"]
            total_buy_cost = row["total_buy_cost"] or 0.0
            total_buy_shares = row["total_buy_shares"] or 0.0
            avg_cost = total_buy_cost / total_buy_shares if total_buy_shares > 0 else 0.0
            cost_basis = shares * avg_cost

            positions.append({
                "portfolio_id": row["portfolio_id"],
                "ticker": row["ticker"],
                "shares": shares,
                "avg_cost": avg_cost,
                "cost_basis": cost_basis,
            })

        return positions


def get_daily_cashflows(portfolio_id: int | None = None) -> dict[str, float]:
    """Get net cashflows per date for TWR calculation.

    Cashflows = buy trades add cash outflow (negative), sell trades add cash inflow (positive).
    Also includes cash_transactions (deposits/withdrawals).

    Args:
        portfolio_id: Optional portfolio ID. If None, aggregates across all portfolios.

    Returns:
        Dict of {date: net_cashflow_eur} where positive = inflow, negative = outflow.
    """
    with get_connection() as conn:
        # Trade cashflows: buys are outflows (-), sells are inflows (+)
        if portfolio_id is not None:
            cur = conn.execute(
                """
                SELECT
                    transaction_date as date,
                    SUM(CASE
                        WHEN transaction_type = 'buy' THEN -shares * price_eur
                        ELSE shares * price_eur
                    END) as net_cf
                FROM transactions
                WHERE portfolio_id = ?
                GROUP BY transaction_date
                """,
                (portfolio_id,),
            )
        else:
            cur = conn.execute(
                """
                SELECT
                    transaction_date as date,
                    SUM(CASE
                        WHEN transaction_type = 'buy' THEN -shares * price_eur
                        ELSE shares * price_eur
                    END) as net_cf
                FROM transactions
                GROUP BY transaction_date
                """
            )

        trade_flows = {row["date"]: row["net_cf"] for row in cur.fetchall()}

        # Cash transaction cashflows: deposits are inflows (+), debits are outflows (-)
        if portfolio_id is not None:
            cur = conn.execute(
                """
                SELECT
                    transaction_date as date,
                    SUM(CASE
                        WHEN cash_type = 'credit' THEN amount_eur
                        ELSE -amount_eur
                    END) as net_cf
                FROM cash_transactions
                WHERE portfolio_id = ?
                GROUP BY transaction_date
                """,
                (portfolio_id,),
            )
        else:
            cur = conn.execute(
                """
                SELECT
                    transaction_date as date,
                    SUM(CASE
                        WHEN cash_type = 'credit' THEN amount_eur
                        ELSE -amount_eur
                    END) as net_cf
                FROM cash_transactions
                GROUP BY transaction_date
                """
            )

        cash_flows = {row["date"]: row["net_cf"] for row in cur.fetchall()}

        # Merge: combine trade and cash flows by date
        all_dates = set(trade_flows.keys()) | set(cash_flows.keys())
        result = {}
        for date in all_dates:
            result[date] = trade_flows.get(date, 0.0) + cash_flows.get(date, 0.0)

        return result


def get_all_sector_allocations(position_values: dict[str, float]) -> list[dict[str, Any]]:
    """Get sector allocations for aggregated positions across all portfolios.

    Args:
        position_values: Dict of {ticker: market_value}

    Returns:
        List of dicts with: sector, value, percentage
    """
    if not position_values:
        return []

    total_value = sum(position_values.values())
    if total_value == 0:
        return []

    with get_connection() as conn:
        tickers = list(position_values.keys())
        placeholders = ",".join("?" for _ in tickers)
        cur = conn.execute(
            f"""
            SELECT ticker, sector
            FROM ticker_sectors
            WHERE ticker IN ({placeholders})
            """,
            tickers,
        )
        ticker_to_sector = {row["ticker"]: row["sector"] for row in cur.fetchall()}

    # Aggregate by sector
    sector_values: dict[str, float] = {}
    for ticker, value in position_values.items():
        sector = ticker_to_sector.get(ticker, "Other")
        sector_values[sector] = sector_values.get(sector, 0.0) + value

    # Sort by value descending, keep top 8 + Other
    sorted_sectors = sorted(sector_values.items(), key=lambda x: x[1], reverse=True)

    result = []
    other_value = 0.0

    for i, (sector, value) in enumerate(sorted_sectors):
        if i < 8 and sector != "Other":
            result.append({
                "sector": sector,
                "value": value,
                "percentage": (value / total_value) * 100,
            })
        else:
            other_value += value

    if other_value > 0:
        result.append({
            "sector": "Other",
            "value": other_value,
            "percentage": (other_value / total_value) * 100,
        })

    return result


def upsert_intraday_prices(ticker: str, trading_day: str, bars: list[dict]) -> None:
    """Upsert intraday prices for a ticker on a specific trading day.

    Deletes existing rows for (ticker, trading_day) with interval='5m',
    then inserts fresh rows in a single transaction.
    """
    from datetime import datetime, timezone

    if not bars:
        return

    with get_connection() as conn:
        # Delete existing intraday data
        conn.execute(
            """
            DELETE FROM price_bars
            WHERE symbol = ?
              AND interval = '5m'
              AND date LIKE ?
            """,
            (ticker, f"{trading_day}%"),
        )

        # Insert fresh intraday bars
        for bar in bars:
            dt = datetime.fromtimestamp(bar["ts"], tz=timezone.utc)
            iso_date = dt.isoformat(timespec="seconds")
            fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

            conn.execute(
                """
                INSERT INTO price_bars (symbol, interval, date, close, fetched_at)
                VALUES (?, '5m', ?, ?, ?)
                """,
                (ticker, iso_date, bar["price"], fetched_at),
            )

        conn.commit()


def get_intraday_prices(tickers: list[str], trading_day: str) -> dict[str, list[dict]]:
    """Get intraday prices for given tickers on a specific trading day."""
    from datetime import datetime

    if not tickers:
        return {}

    with get_connection() as conn:
        placeholders = ",".join("?" for _ in tickers)
        cur = conn.execute(
            f"""
            SELECT symbol, date, close
            FROM price_bars
            WHERE symbol IN ({placeholders})
              AND interval = '5m'
              AND date LIKE ?
            ORDER BY symbol, date ASC
            """,
            (*tickers, f"{trading_day}%"),
        )
        rows = cur.fetchall()

        result: dict[str, list[dict]] = {s: [] for s in tickers}
        for row in rows:
            dt = datetime.fromisoformat(row["date"])
            unix_ts = int(dt.timestamp())

            result[row["symbol"]].append({
                "ts": unix_ts,
                "price": row["close"],
            })

        return result
