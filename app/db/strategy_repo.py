"""Repository for saved backtest strategies and portfolio assignments."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.connection import get_connection


def list_saved_strategies(portfolio_id: int, ticker: str) -> list[dict]:
    """List all saved strategies for a portfolio-ticker pair.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol

    Returns:
        List of dicts with keys: id, name, base_strategy_key, updated_at
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT id, name, base_strategy_key, updated_at
            FROM saved_strategies
            WHERE portfolio_id = ? AND ticker = ?
            ORDER BY updated_at DESC
            """,
            (portfolio_id, ticker.upper()),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "base_strategy_key": row[2],
                "updated_at": row[3],
            }
            for row in rows
        ]


def get_saved_strategy(portfolio_id: int, ticker: str, strategy_id: int) -> dict | None:
    """Get a saved strategy by ID including full params.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol
        strategy_id: Saved strategy ID

    Returns:
        Dict with keys: id, name, base_strategy_key, params (dict), notes, created_at, updated_at
        None if not found
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT id, name, base_strategy_key, params_json, notes, created_at, updated_at
            FROM saved_strategies
            WHERE portfolio_id = ? AND ticker = ? AND id = ?
            """,
            (portfolio_id, ticker.upper(), strategy_id),
        )
        row = cur.fetchone()
        if not row:
            return None

        params_dict = json.loads(row[3]) if row[3] else {}

        return {
            "id": row[0],
            "name": row[1],
            "base_strategy_key": row[2],
            "params": params_dict,
            "notes": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }


def upsert_saved_strategy(
    portfolio_id: int,
    ticker: str,
    name: str,
    base_strategy_key: str,
    params: dict,
    notes: str | None = None,
) -> int:
    """Create or update a saved strategy.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol
        name: Strategy name (unique per portfolio-ticker)
        base_strategy_key: Base strategy key (e.g., "ema_crossover_rsi")
        params: Parameter dict
        notes: Optional notes

    Returns:
        Saved strategy ID
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    params_json = json.dumps(params)

    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO saved_strategies
                (portfolio_id, ticker, name, base_strategy_key, params_json, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(portfolio_id, ticker, name) DO UPDATE SET
                base_strategy_key = excluded.base_strategy_key,
                params_json = excluded.params_json,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (portfolio_id, ticker.upper(), name, base_strategy_key, params_json, notes, now, now),
        )
        conn.commit()

        # Get the inserted/updated ID
        cur = conn.execute(
            """
            SELECT id FROM saved_strategies
            WHERE portfolio_id = ? AND ticker = ? AND name = ?
            """,
            (portfolio_id, ticker.upper(), name),
        )
        row = cur.fetchone()
        return row[0] if row else 0

    finally:
        conn.close()


def delete_saved_strategy(portfolio_id: int, ticker: str, strategy_id: int) -> None:
    """Delete a saved strategy.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol
        strategy_id: Saved strategy ID
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            DELETE FROM saved_strategies
            WHERE portfolio_id = ? AND ticker = ? AND id = ?
            """,
            (portfolio_id, ticker.upper(), strategy_id),
        )
        conn.commit()
    finally:
        conn.close()


def assign_saved_strategy(portfolio_id: int, ticker: str, saved_strategy_id: int) -> None:
    """Assign a saved strategy to a ticker for portfolio use.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol
        saved_strategy_id: Saved strategy ID to assign
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn = get_connection()
    try:
        conn.execute(
            """
            REPLACE INTO ticker_strategy_assignment
                (portfolio_id, ticker, saved_strategy_id, assigned_at)
            VALUES (?, ?, ?, ?)
            """,
            (portfolio_id, ticker.upper(), saved_strategy_id, now),
        )
        conn.commit()
    finally:
        conn.close()


def get_assignment(portfolio_id: int, ticker: str) -> dict | None:
    """Get the assigned strategy for a ticker.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker symbol

    Returns:
        Dict with keys: saved_strategy_id, assigned_at
        None if no assignment
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT saved_strategy_id, assigned_at
            FROM ticker_strategy_assignment
            WHERE portfolio_id = ? AND ticker = ?
            """,
            (portfolio_id, ticker.upper()),
        )
        row = cur.fetchone()
        if not row:
            return None

        return {
            "saved_strategy_id": row[0],
            "assigned_at": row[1],
        }


def get_assignment_map(portfolio_id: int) -> dict[str, int]:
    """Get all strategy assignments for a portfolio.

    Args:
        portfolio_id: Portfolio ID

    Returns:
        Dict mapping {ticker: saved_strategy_id}
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT ticker, saved_strategy_id
            FROM ticker_strategy_assignment
            WHERE portfolio_id = ?
            ORDER BY ticker ASC
            """,
            (portfolio_id,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def get_saved_strategy_by_id(portfolio_id: int, strategy_id: int) -> dict | None:
    """Get a saved strategy by ID without requiring ticker.

    Args:
        portfolio_id: Portfolio ID
        strategy_id: Saved strategy ID

    Returns:
        Dict with keys: id, ticker, name, base_strategy_key, params (dict), notes, created_at, updated_at
        None if not found
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT id, ticker, name, base_strategy_key, params_json, notes, created_at, updated_at
            FROM saved_strategies
            WHERE portfolio_id = ? AND id = ?
            """,
            (portfolio_id, strategy_id),
        )
        row = cur.fetchone()
        if not row:
            return None

        params_dict = json.loads(row[4]) if row[4] else {}

        return {
            "id": row[0],
            "ticker": row[1],
            "name": row[2],
            "base_strategy_key": row[3],
            "params": params_dict,
            "notes": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------


def add_to_watchlist(portfolio_id: int, ticker: str, notes: str = "") -> None:
    """Add a ticker to the watchlist.  No-op if already present.

    Args:
        portfolio_id: Portfolio ID
        ticker:       Stock ticker symbol
        notes:        Optional note (e.g. "potential breakout candidate")
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO watchlist (portfolio_id, ticker, notes, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (portfolio_id, ticker.upper(), notes, now),
        )
        conn.commit()
    finally:
        conn.close()


def remove_from_watchlist(portfolio_id: int, ticker: str) -> None:
    """Remove a ticker from the watchlist.

    Args:
        portfolio_id: Portfolio ID
        ticker:       Stock ticker symbol
    """
    conn = get_connection()
    try:
        conn.execute(
            "DELETE FROM watchlist WHERE portfolio_id = ? AND ticker = ?",
            (portfolio_id, ticker.upper()),
        )
        conn.commit()
    finally:
        conn.close()


def list_watchlist(portfolio_id: int) -> list[dict]:
    """List all watchlist tickers for a portfolio.

    Returns:
        List of dicts with keys: ticker, notes, added_at
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT ticker, notes, added_at
            FROM watchlist
            WHERE portfolio_id = ?
            ORDER BY ticker ASC
            """,
            (portfolio_id,),
        )
        return [{"ticker": row[0], "notes": row[1], "added_at": row[2]} for row in cur.fetchall()]
