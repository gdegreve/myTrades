from __future__ import annotations

from typing import Any

from app.db.connection import get_connection


def list_trades(portfolio_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Return all stock/ETF trades for a portfolio, ordered by date ascending.

    This is the primary ledger source for position computation.
    Includes all buy/sell transactions with their full details.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                id,
                ticker,
                transaction_type,
                shares,
                price,
                price_currency,
                price_eur,
                fx_rate,
                commission,
                transaction_date,
                notes
            FROM transactions
            WHERE portfolio_id = ?
            ORDER BY transaction_date ASC, id ASC
            LIMIT ?
            """,
            (portfolio_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def list_cash_movements(portfolio_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Return all cash deposits/withdrawals for a portfolio, ordered by date ascending.

    This is the primary ledger source for cash balance computation.
    Includes all credit (deposit) and debit (withdrawal) transactions.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                id,
                cash_type,
                amount_eur,
                transaction_date,
                notes
            FROM cash_transactions
            WHERE portfolio_id = ?
            ORDER BY transaction_date ASC, id ASC
            LIMIT ?
            """,
            (portfolio_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def list_ledger_entries(portfolio_id: int, limit: int = 50) -> dict[str, Any]:
    """Return unified ledger view combining trades and cash movements.

    Returns a dict with 'trades' and 'cash_movements' keys, each containing
    their respective ledger entries ordered chronologically.
    """
    return {
        "trades": list_trades(portfolio_id, limit),
        "cash_movements": list_cash_movements(portfolio_id, limit),
    }


def get_ticker_sectors(portfolio_id: int) -> dict[str, str]:
    """Return sector mapping for all tickers in portfolio transactions.

    Returns dict of {ticker: sector_name}, empty string if sector not found.
    Used for data completeness checks.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT DISTINCT t.ticker, COALESCE(ts.sector, '') as sector
            FROM transactions t
            LEFT JOIN ticker_sectors ts ON t.ticker = ts.ticker
            WHERE t.portfolio_id = ?
            ORDER BY t.ticker
            """,
            (portfolio_id,),
        )
        return {row["ticker"]: row["sector"] for row in cur.fetchall()}


def get_ticker_regions(portfolio_id: int) -> dict[str, str]:
    """Return region mapping for all tickers in portfolio transactions.

    Returns dict of {ticker: region_name}, empty string if region not found.
    Used for drift analysis and data completeness checks.
    """
    with get_connection() as conn:
        # Check if ticker_regions table exists
        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ticker_regions'"
        ).fetchone()

        if not table_check:
            # Return empty dict if table doesn't exist yet
            return {}

        cur = conn.execute(
            """
            SELECT DISTINCT t.ticker, COALESCE(tr.region, '') as region
            FROM transactions t
            LEFT JOIN ticker_regions tr ON t.ticker = tr.ticker
            WHERE t.portfolio_id = ?
            ORDER BY t.ticker
            """,
            (portfolio_id,),
        )
        return {row["ticker"]: row["region"] for row in cur.fetchall()}


def insert_cash_transaction(
    portfolio_id: int,
    cash_type: str,
    amount_eur: float,
    transaction_date: str,
    notes: str = "",
) -> None:
    """Insert a cash transaction into the ledger.

    Args:
        portfolio_id: Portfolio ID
        cash_type: 'credit' (deposit) or 'debit' (withdrawal)
        amount_eur: Amount in EUR (positive)
        transaction_date: Date in ISO format (YYYY-MM-DD)
        notes: Optional description

    Raises:
        sqlite3.Error on database error
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO cash_transactions (portfolio_id, cash_type, amount_eur, transaction_date, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (portfolio_id, cash_type, amount_eur, transaction_date, notes),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_trade(
    portfolio_id: int,
    ticker: str,
    transaction_type: str,
    shares: float,
    price_eur: float,
    commission: float,
    transaction_date: str,
    notes: str = "",
) -> None:
    """Insert a trade transaction into the ledger.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol
        transaction_type: 'buy' or 'sell'
        shares: Number of shares (positive)
        price_eur: Price per share in EUR
        commission: Commission/fees in EUR
        transaction_date: Date in ISO format (YYYY-MM-DD)
        notes: Optional description

    Raises:
        sqlite3.Error on database error
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO transactions (
                portfolio_id,
                ticker,
                transaction_type,
                shares,
                price,
                price_eur,
                commission,
                transaction_date,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                ticker.upper(),
                transaction_type,
                shares,
                price_eur,  # Store as both price and price_eur for simplicity
                price_eur,
                commission,
                transaction_date,
                notes,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
