"""Repository for backtest results caching."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone

from app.db.connection import get_connection


def _compute_params_hash(params: dict) -> str:
    """Compute SHA1 hash of params dict for cache key.

    Args:
        params: Strategy parameters dict

    Returns:
        Hex string of SHA1 hash
    """
    params_str = json.dumps(params, sort_keys=True)
    return hashlib.sha1(params_str.encode()).hexdigest()


def get_cached_backtest(
    portfolio_id: int,
    ticker: str,
    strategy_key: str,
    params: dict,
    timeframe: str,
) -> dict | None:
    """Get cached backtest result if it exists.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker
        strategy_key: Strategy key (e.g., "ema_crossover_rsi")
        params: Strategy parameters dict
        timeframe: Timeframe string (e.g., "1y", "6mo")

    Returns:
        Result dict with keys: stats, equity_series, trades
        None if not cached
    """
    params_hash = _compute_params_hash(params)

    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT result_json, created_at
            FROM backtest_cache
            WHERE portfolio_id = ? AND ticker = ? AND strategy_key = ?
                AND params_hash = ? AND timeframe = ?
            """,
            (portfolio_id, ticker.upper(), strategy_key, params_hash, timeframe),
        )
        row = cur.fetchone()

        if not row:
            return None

        result_dict = json.loads(row[0])
        result_dict["cached_at"] = row[1]
        return result_dict


def upsert_cached_backtest(
    portfolio_id: int,
    ticker: str,
    strategy_key: str,
    params: dict,
    timeframe: str,
    result_dict: dict,
) -> None:
    """Store backtest result in cache.

    Args:
        portfolio_id: Portfolio ID
        ticker: Stock ticker
        strategy_key: Strategy key
        params: Strategy parameters dict
        timeframe: Timeframe string
        result_dict: Result dict with stats, equity_series, trades
    """
    params_hash = _compute_params_hash(params)
    result_json = json.dumps(result_dict)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    conn = get_connection()
    try:
        conn.execute(
            """
            REPLACE INTO backtest_cache
                (portfolio_id, ticker, strategy_key, params_hash, timeframe, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (portfolio_id, ticker.upper(), strategy_key, params_hash, timeframe, result_json, now),
        )
        conn.commit()
    finally:
        conn.close()
