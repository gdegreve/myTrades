from __future__ import annotations

from typing import Any

from app.db.connection import get_connection


def _table_exists(conn, name: str) -> bool:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    )
    return cur.fetchone() is not None


def _column_exists(conn, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in cur.fetchall())


def load_policy_snapshot(portfolio_id: int) -> dict[str, Any]:
    """Return a snapshot for the Design page (policy + sector targets + region targets + base currency).""

    This function is intentionally read-only and safe to call from callbacks.
    """
    conn = get_connection()
    try:
        snapshot: dict[str, Any] = {"policy": {}, "sector_targets": [], "region_targets": [], "base_currency": "EUR"}

        # Validate portfolio exists (optional, defensive)
        if _table_exists(conn, "portfolios"):
            row = conn.execute(
                "SELECT id FROM portfolios WHERE id=?",
                (portfolio_id,),
            ).fetchone()
            if row is None:
                return snapshot

        # Load policy (if table exists and row present)
        if _table_exists(conn, "portfolio_policy"):
            prow = conn.execute(
                """
                SELECT
                    benchmark_ticker,
                    risk_profile,
                    cash_min_pct,
                    cash_target_pct,
                    cash_max_pct,
                    max_position_pct,
                    max_sector_pct,
                    rebalance_freq,
                    drift_trigger_pct,
                    rebalance_method,
                    signal_sizing_mode,
                    signal_step_pct,
                    signal_strong_step_pct,
                    signal_exit_threshold_pct,
                    signal_min_trade_eur,
                    signal_risk_per_trade_pct,
                    signal_atr_period,
                    signal_atr_mult,
                    signal_stop_source,
                    signal_stop_order_type,
                    signal_stop_limit_buffer_bps
                FROM portfolio_policy
                WHERE portfolio_id=?
                """,
                (portfolio_id,),
            ).fetchone()
            if prow:
                snapshot["policy"] = dict(prow)

        # Load sector targets (support both schemas: sector_name or sector)
        if _table_exists(conn, "portfolio_sector_targets"):
            if _column_exists(conn, "portfolio_sector_targets", "sector_name"):
                sector_col = "sector_name"
            else:
                sector_col = "sector"

            rows = conn.execute(
                f"""
                SELECT {sector_col} AS sector,
                       target_pct AS target_pct,
                       min_pct AS min_pct,
                       max_pct AS max_pct
                FROM portfolio_sector_targets
                WHERE portfolio_id=?
                ORDER BY {sector_col} COLLATE NOCASE
                """,
                (portfolio_id,),
            ).fetchall()
            snapshot["sector_targets"] = [dict(r) for r in rows]

        # Fallback: if no saved targets, derive sector list from holdings + ticker_sectors (if available)
        if not snapshot["sector_targets"] and _table_exists(conn, "holdings") and _table_exists(conn, "ticker_sectors"):
            rows = conn.execute(
                """
                SELECT DISTINCT COALESCE(ts.sector, 'Unknown') AS sector
                FROM holdings h
                LEFT JOIN ticker_sectors ts ON ts.ticker = h.ticker
                WHERE h.portfolio_id=?
                ORDER BY sector COLLATE NOCASE
                """,
                (portfolio_id,),
            ).fetchall()

            sectors = [r["sector"] for r in rows if r and r["sector"]]
            snapshot["sector_targets"] = [
                {"sector": s, "target_pct": None, "min_pct": None, "max_pct": None} for s in sectors
            ]

        # Load region targets
        if _table_exists(conn, "portfolio_region_targets"):
            rows = conn.execute(
                """
                SELECT region_name AS region,
                       target_pct AS target_pct,
                       min_pct AS min_pct,
                       max_pct AS max_pct
                FROM portfolio_region_targets
                WHERE portfolio_id=?
                ORDER BY region_name COLLATE NOCASE
                """,
                (portfolio_id,),
            ).fetchall()
            snapshot["region_targets"] = [dict(r) for r in rows]

        # Fallback: if no saved region targets, derive from holdings + ticker_regions
        if not snapshot["region_targets"] and _table_exists(conn, "ticker_regions"):
            # Try to get current holdings from transactions (ledger-based)
            if _table_exists(conn, "transactions"):
                rows = conn.execute(
                    """
                    SELECT DISTINCT COALESCE(tr.region, 'Unknown') AS region
                    FROM transactions t
                    LEFT JOIN ticker_regions tr ON tr.ticker = t.ticker
                    WHERE t.portfolio_id=? AND t.transaction_type IN ('buy', 'sell')
                    ORDER BY region COLLATE NOCASE
                    """,
                    (portfolio_id,),
                ).fetchall()

                regions = [r["region"] for r in rows if r and r["region"]]
                if regions:
                    # Equal-weight fallback targets (not saved to DB)
                    equal_weight = 100.0 / len(regions) if regions else 0.0
                    snapshot["region_targets"] = [
                        {"region": r, "target_pct": equal_weight, "min_pct": None, "max_pct": None} for r in regions
                    ]

        return snapshot
    finally:
        conn.close()


def save_policy_snapshot(
    portfolio_id: int,
    policy: dict[str, Any],
    sector_targets: list[dict[str, Any]],
    region_targets: list[dict[str, Any]] | None = None,
) -> None:
    """Save policy + sector targets + region targets in a single transaction.

    Validation is expected to happen in the callback layer.
    This function trusts input and writes atomically.
    """
    if region_targets is None:
        region_targets = []
    conn = get_connection()
    try:
        cur = conn.cursor()

        # Upsert policy
        cur.execute(
            """
            INSERT INTO portfolio_policy (
                portfolio_id,
                benchmark_ticker,
                risk_profile,
                cash_min_pct,
                cash_target_pct,
                cash_max_pct,
                max_position_pct,
                max_sector_pct,
                rebalance_freq,
                drift_trigger_pct,
                rebalance_method,
                signal_sizing_mode,
                signal_step_pct,
                signal_strong_step_pct,
                signal_exit_threshold_pct,
                signal_min_trade_eur,
                signal_risk_per_trade_pct,
                signal_atr_period,
                signal_atr_mult,
                signal_stop_source,
                signal_stop_order_type,
                signal_stop_limit_buffer_bps,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(portfolio_id) DO UPDATE SET
                benchmark_ticker = excluded.benchmark_ticker,
                risk_profile = excluded.risk_profile,
                cash_min_pct = excluded.cash_min_pct,
                cash_target_pct = excluded.cash_target_pct,
                cash_max_pct = excluded.cash_max_pct,
                max_position_pct = excluded.max_position_pct,
                max_sector_pct = excluded.max_sector_pct,
                rebalance_freq = excluded.rebalance_freq,
                drift_trigger_pct = excluded.drift_trigger_pct,
                rebalance_method = excluded.rebalance_method,
                signal_sizing_mode = excluded.signal_sizing_mode,
                signal_step_pct = excluded.signal_step_pct,
                signal_strong_step_pct = excluded.signal_strong_step_pct,
                signal_exit_threshold_pct = excluded.signal_exit_threshold_pct,
                signal_min_trade_eur = excluded.signal_min_trade_eur,
                signal_risk_per_trade_pct = excluded.signal_risk_per_trade_pct,
                signal_atr_period = excluded.signal_atr_period,
                signal_atr_mult = excluded.signal_atr_mult,
                signal_stop_source = excluded.signal_stop_source,
                signal_stop_order_type = excluded.signal_stop_order_type,
                signal_stop_limit_buffer_bps = excluded.signal_stop_limit_buffer_bps,
                updated_at = excluded.updated_at
            """,
            (
                portfolio_id,
                policy.get("benchmark_ticker"),
                policy.get("risk_profile"),
                policy.get("cash_min_pct"),
                policy.get("cash_target_pct"),
                policy.get("cash_max_pct"),
                policy.get("max_position_pct"),
                policy.get("max_sector_pct"),
                policy.get("rebalance_freq"),
                policy.get("drift_trigger_pct"),
                policy.get("rebalance_method"),
                policy.get("signal_sizing_mode", "off"),
                policy.get("signal_step_pct", 1.0),
                policy.get("signal_strong_step_pct", 2.0),
                policy.get("signal_exit_threshold_pct", 0.5),
                policy.get("signal_min_trade_eur", 250.0),
                policy.get("signal_risk_per_trade_pct", 0.5),
                policy.get("signal_atr_period", 14),
                policy.get("signal_atr_mult", 2.0),
                policy.get("signal_stop_source", "strategy_stop"),
                policy.get("signal_stop_order_type", "stop_limit"),
                policy.get("signal_stop_limit_buffer_bps", 25.0),
            ),
        )

        # Clear existing sector targets
        cur.execute(
            "DELETE FROM portfolio_sector_targets WHERE portfolio_id=?",
            (portfolio_id,),
        )

        # Insert new sector targets (support both schema variants)
        if _table_exists(conn, "portfolio_sector_targets"):
            if _column_exists(conn, "portfolio_sector_targets", "sector_name"):
                sector_col = "sector_name"
            else:
                sector_col = "sector"

            for target in sector_targets:
                cur.execute(
                    f"""
                    INSERT INTO portfolio_sector_targets
                        (portfolio_id, {sector_col}, target_pct, min_pct, max_pct)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        portfolio_id,
                        target.get("sector"),
                        target.get("target_pct"),
                        target.get("min_pct"),
                        target.get("max_pct"),
                    ),
                )

        # Clear existing region targets
        cur.execute(
            "DELETE FROM portfolio_region_targets WHERE portfolio_id=?",
            (portfolio_id,),
        )

        # Insert new region targets
        if _table_exists(conn, "portfolio_region_targets"):
            for target in region_targets:
                cur.execute(
                    """
                    INSERT INTO portfolio_region_targets
                        (portfolio_id, region_name, target_pct, min_pct, max_pct)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        portfolio_id,
                        target.get("region"),
                        target.get("target_pct"),
                        target.get("min_pct"),
                        target.get("max_pct"),
                    ),
                )

        conn.commit()
    finally:
        conn.close()


# Backwards-compatible alias
def load_policy(portfolio_id: int) -> dict[str, Any]:
    return load_policy_snapshot(portfolio_id)
