from __future__ import annotations

from typing import Any

from app.db.connection import get_connection


def list_strategy_definitions() -> list[dict[str, Any]]:
    """Return all available strategy definitions.

    Returns list of strategy definitions with their metadata.
    Used for populating strategy dropdowns and displaying strategy info.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                strategy_key,
                name,
                description,
                params_json,
                updated_at
            FROM strategy_definitions
            ORDER BY name ASC
            """
        )
        return [dict(r) for r in cur.fetchall()]


def get_ticker_strategy_map(portfolio_id: int) -> dict[str, str]:
    """Return strategy assignments for all tickers in a portfolio.

    Returns dict of {ticker: strategy_key}.
    Empty dict if no assignments exist.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT ticker, strategy_key
            FROM ticker_strategy_map
            WHERE portfolio_id = ?
            ORDER BY ticker ASC
            """,
            (portfolio_id,),
        )
        return {row["ticker"]: row["strategy_key"] for row in cur.fetchall()}


def upsert_ticker_strategy(portfolio_id: int, ticker: str, strategy_key: str) -> None:
    """Assign a strategy to a ticker for a portfolio.

    Updates if mapping exists, inserts if new.
    Uses REPLACE for simplicity (SQLite upsert).

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol
        strategy_key: Strategy identifier

    Raises:
        sqlite3.Error on database error
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute(
            """
            REPLACE INTO ticker_strategy_map (portfolio_id, ticker, strategy_key, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (portfolio_id, ticker.upper(), strategy_key, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_signals_backlog(portfolio_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Return signals backlog for a portfolio, ordered by timestamp descending.

    Returns recent signals from the backlog for review and audit.

    Args:
        portfolio_id: Portfolio ID
        limit: Maximum number of records to return (default 100)

    Returns:
        List of signal records with all metadata
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                id,
                portfolio_id,
                ts,
                ticker,
                strategy_key,
                signal,
                reason,
                meta_json
            FROM signals_backlog
            WHERE portfolio_id = ?
            ORDER BY ts DESC
            LIMIT ?
            """,
            (portfolio_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
