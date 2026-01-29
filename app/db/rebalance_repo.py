from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db.connection import get_connection


# ============================================================================
# AI Settings Functions
# ============================================================================


def get_ai_settings(portfolio_id: int) -> dict[str, Any]:
    """Return AI settings for a portfolio, or defaults if not configured.

    Returns:
        dict with keys: portfolio_id, base_url, model, enabled, timeout_ms, updated_at
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                portfolio_id,
                base_url,
                model,
                enabled,
                timeout_ms,
                updated_at
            FROM ai_settings
            WHERE portfolio_id = ?
            """,
            (portfolio_id,),
        )
        row = cur.fetchone()

        if row:
            return dict(row)

        # Return defaults if no settings exist
        return {
            "portfolio_id": portfolio_id,
            "base_url": "http://192.168.129.55:11434",
            "model": "llama3.1:8b",
            "enabled": 1,
            "timeout_ms": 30000,
            "updated_at": None,
        }


def upsert_ai_settings(
    portfolio_id: int,
    base_url: str,
    model: str,
    enabled: bool,
    timeout_ms: int,
) -> None:
    """Create or update AI settings for a portfolio.

    Args:
        portfolio_id: Portfolio ID
        base_url: AI model endpoint URL
        model: Model identifier (e.g., "llama3.1:8b")
        enabled: Whether AI review is enabled
        timeout_ms: Request timeout in milliseconds

    Raises:
        sqlite3.Error on database error
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO ai_settings (portfolio_id, base_url, model, enabled, timeout_ms, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(portfolio_id) DO UPDATE SET
                base_url = excluded.base_url,
                model = excluded.model,
                enabled = excluded.enabled,
                timeout_ms = excluded.timeout_ms,
                updated_at = excluded.updated_at
            """,
            (portfolio_id, base_url, model, int(enabled), timeout_ms, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================================
# AI Job Cache Functions
# ============================================================================


def get_cached_ai_job(
    portfolio_id: int,
    eod_date: str,
    plan_hash: str,
    model: str,
) -> dict[str, Any] | None:
    """Retrieve a cached AI job by lookup key.

    Args:
        portfolio_id: Portfolio ID
        eod_date: End-of-day date in ISO format (YYYY-MM-DD)
        plan_hash: Hash of rebalance plan for cache invalidation
        model: Model identifier

    Returns:
        Job record dict if found, None otherwise
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                id,
                portfolio_id,
                eod_date,
                plan_hash,
                model,
                status,
                result,
                created_at,
                completed_at
            FROM ai_job_cache
            WHERE portfolio_id = ?
              AND eod_date = ?
              AND plan_hash = ?
              AND model = ?
            """,
            (portfolio_id, eod_date, plan_hash, model),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_ai_job(
    portfolio_id: int,
    eod_date: str,
    plan_hash: str,
    model: str,
) -> int:
    """Create a new AI job record (idempotent via INSERT OR IGNORE).

    Args:
        portfolio_id: Portfolio ID
        eod_date: End-of-day date in ISO format (YYYY-MM-DD)
        plan_hash: Hash of rebalance plan for cache invalidation
        model: Model identifier

    Returns:
        Job ID (newly created or existing)

    Raises:
        sqlite3.Error on database error
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            INSERT OR IGNORE INTO ai_job_cache (portfolio_id, eod_date, plan_hash, model, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (portfolio_id, eod_date, plan_hash, model),
        )

        conn.commit()

        # Retrieve the job_id (either newly created or existing)
        cur.execute(
            """
            SELECT id
            FROM ai_job_cache
            WHERE portfolio_id = ?
              AND eod_date = ?
              AND plan_hash = ?
              AND model = ?
            """,
            (portfolio_id, eod_date, plan_hash, model),
        )
        row = cur.fetchone()
        return row["id"] if row else -1

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_ai_job(
    job_id: int,
    status: str,
    result: str | None = None,
) -> None:
    """Update AI job status and optionally store result.

    Args:
        job_id: Job ID to update
        status: New status ('pending', 'running', 'completed', 'failed')
        result: Optional result text (AI review output)

    Raises:
        sqlite3.Error on database error
    """
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # If status is completed or failed, update completed_at timestamp
        if status in ("completed", "failed"):
            conn.execute(
                """
                UPDATE ai_job_cache
                SET status = ?,
                    result = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (status, result, now, job_id),
            )
        else:
            conn.execute(
                """
                UPDATE ai_job_cache
                SET status = ?,
                    result = ?
                WHERE id = ?
                """,
                (status, result, job_id),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_ai_job_by_id(job_id: int) -> dict[str, Any] | None:
    """Retrieve an AI job by its ID.

    Args:
        job_id: Job ID

    Returns:
        Job record dict if found, None otherwise
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT
                id,
                portfolio_id,
                eod_date,
                plan_hash,
                model,
                status,
                result,
                created_at,
                completed_at
            FROM ai_job_cache
            WHERE id = ?
            """,
            (job_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# ============================================================================
# Rebalance Data Helper Functions
# ============================================================================


def get_signals_for_portfolio(portfolio_id: int) -> list[dict[str, Any]]:
    """Return all signals from signals_backlog table for a portfolio.

    Returns signals ordered by timestamp descending (most recent first).

    Args:
        portfolio_id: Portfolio ID

    Returns:
        List of signal dicts with keys: id, portfolio_id, ts, ticker, strategy_key, signal, reason, meta_json
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
            """,
            (portfolio_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_current_drift(portfolio_id: int) -> dict[str, Any]:
    """Compute current sector/region/cash drift vs policy targets.

    This is a read-only computation for rebalance decision support.

    Args:
        portfolio_id: Portfolio ID

    Returns:
        dict with keys:
            - sector_drift: dict of {sector_name: drift_pct}
            - region_drift: dict of {region_name: drift_pct}
            - cash_drift_pct: float (actual cash % - target cash %)
            - holdings_value: float (total market value of holdings)
            - cash_balance: float (current cash)

    Notes:
        - Requires price_bars table for current market prices
        - Returns zero drift if holdings or policy targets are missing
        - Sector/region mappings come from ticker_sectors and ticker_regions tables
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

        # Get holdings with latest prices (requires price_bars table)
        cur = conn.execute(
            """
            SELECT
                h.ticker,
                h.total_shares,
                COALESCE(pb.close, h.avg_cost) AS current_price,
                ts.sector,
                tr.region
            FROM holdings h
            LEFT JOIN ticker_sectors ts ON ts.ticker = h.ticker
            LEFT JOIN ticker_regions tr ON tr.ticker = h.ticker
            LEFT JOIN (
                SELECT symbol, close
                FROM price_bars
                WHERE (symbol, date) IN (
                    SELECT symbol, MAX(date)
                    FROM price_bars
                    GROUP BY symbol
                )
            ) pb ON pb.symbol = h.ticker
            WHERE h.portfolio_id = ?
            """,
            (portfolio_id,),
        )
        holdings = [dict(r) for r in cur.fetchall()]

        # Compute holdings value
        holdings_value = sum(h["total_shares"] * h["current_price"] for h in holdings)
        total_value = holdings_value + cash_balance

        if total_value == 0:
            return {
                "sector_drift": {},
                "region_drift": {},
                "cash_drift_pct": 0.0,
                "holdings_value": 0.0,
                "cash_balance": cash_balance,
            }

        # Compute actual allocations
        sector_actual = {}
        region_actual = {}

        for h in holdings:
            position_value = h["total_shares"] * h["current_price"]
            position_pct = (position_value / total_value) * 100.0

            sector = h["sector"] or "Unknown"
            region = h["region"] or "Unknown"

            sector_actual[sector] = sector_actual.get(sector, 0.0) + position_pct
            region_actual[region] = region_actual.get(region, 0.0) + position_pct

        # Get target allocations from policy
        cur = conn.execute(
            """
            SELECT sector_name, target_pct
            FROM portfolio_sector_targets
            WHERE portfolio_id = ?
            """,
            (portfolio_id,),
        )
        sector_targets = {r["sector_name"]: r["target_pct"] for r in cur.fetchall()}

        cur = conn.execute(
            """
            SELECT region_name, target_pct
            FROM portfolio_region_targets
            WHERE portfolio_id = ?
            """,
            (portfolio_id,),
        )
        region_targets = {r["region_name"]: r["target_pct"] for r in cur.fetchall()}

        cur = conn.execute(
            """
            SELECT cash_target_pct
            FROM portfolio_policy
            WHERE portfolio_id = ?
            """,
            (portfolio_id,),
        )
        row = cur.fetchone()
        cash_target_pct = row["cash_target_pct"] if row else 0.0

        # Compute drift
        sector_drift = {}
        for sector, target in sector_targets.items():
            actual = sector_actual.get(sector, 0.0)
            sector_drift[sector] = actual - target

        region_drift = {}
        for region, target in region_targets.items():
            actual = region_actual.get(region, 0.0)
            region_drift[region] = actual - target

        actual_cash_pct = (cash_balance / total_value) * 100.0
        cash_drift_pct = actual_cash_pct - cash_target_pct

        return {
            "sector_drift": sector_drift,
            "region_drift": region_drift,
            "cash_drift_pct": cash_drift_pct,
            "holdings_value": holdings_value,
            "cash_balance": cash_balance,
        }
