from __future__ import annotations

from typing import Any

from app.db.connection import get_connection


def get_portfolio_holdings(portfolio_id: int) -> list[dict[str, Any]]:
    """Return current holdings for a portfolio."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                ticker,
                total_shares,
                avg_cost,
                last_updated
            FROM holdings
            WHERE portfolio_id = ?
            ORDER BY ticker
            """,
            (portfolio_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_recent_cash_transactions(portfolio_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Return recent cash transactions for a portfolio."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                transaction_date,
                cash_type,
                amount_eur,
                notes
            FROM cash_transactions
            WHERE portfolio_id = ?
            ORDER BY transaction_date DESC, id DESC
            LIMIT ?
            """,
            (portfolio_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_recent_trades(portfolio_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Return recent trades for a portfolio."""
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                transaction_date,
                transaction_type,
                ticker,
                shares,
                price_eur,
                commission,
                notes
            FROM transactions
            WHERE portfolio_id = ?
            ORDER BY transaction_date DESC, id DESC
            LIMIT ?
            """,
            (portfolio_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def get_portfolio_kpis(portfolio_id: int) -> dict[str, Any]:
    """Return computed KPIs for a portfolio.

    Returns:
        - cash_balance: from portfolios table
        - invested_amount: sum of (total_shares * avg_cost) from holdings
        - total_value: placeholder (requires market prices)
        - unrealized_pnl: placeholder (requires market prices)
    """
    with get_connection() as conn:
        # Get cash balance
        cur = conn.execute(
            """
            SELECT cash_balance
            FROM portfolios
            WHERE id = ?
            """,
            (portfolio_id,),
        )
        row = cur.fetchone()
        cash_balance = row["cash_balance"] if row else 0.0

        # Get invested amount (cost basis)
        cur = conn.execute(
            """
            SELECT SUM(total_shares * avg_cost) as invested
            FROM holdings
            WHERE portfolio_id = ?
            """,
            (portfolio_id,),
        )
        row = cur.fetchone()
        invested_amount = row["invested"] if row and row["invested"] else 0.0

        return {
            "cash_balance": cash_balance,
            "invested_amount": invested_amount,
            "total_value": None,  # Placeholder: requires market prices
            "unrealized_pnl": None,  # Placeholder: requires market prices
        }
