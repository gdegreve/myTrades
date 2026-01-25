from __future__ import annotations

from datetime import datetime, timezone

from app.db.connection import get_connection


def ensure_schema() -> None:
    """Create (or upgrade) the DB schema required by the Dash app.

    This is intentionally tiny and idempotent: safe to call on every start.
    """
    with get_connection() as con:
        cur = con.cursor()

        # Policy table (one row per portfolio).
        # Keep this minimal and extendable. Fields can be added later via migrations.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_policy (
                portfolio_id INTEGER PRIMARY KEY,
                benchmark_ticker TEXT,
                risk_profile TEXT,
                base_currency TEXT DEFAULT 'EUR',

                cash_min_pct REAL DEFAULT 0.0,
                cash_target_pct REAL DEFAULT 0.0,
                cash_max_pct REAL DEFAULT 0.0,

                max_position_pct REAL DEFAULT 0.0,
                max_sector_pct REAL DEFAULT 0.0,

                rebalance_freq TEXT DEFAULT 'quarterly',
                drift_trigger_pct REAL DEFAULT 0.0,
                rebalance_method TEXT DEFAULT 'contributions_first',

                updated_at TEXT
            );
            """
        )

        # Sector targets table (already exists in your DB, but keep creation for robustness).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_sector_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER NOT NULL,
                sector_name TEXT NOT NULL,
                target_pct REAL NOT NULL,
                min_pct REAL NOT NULL,
                max_pct REAL NOT NULL
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sector_targets_portfolio
            ON portfolio_sector_targets(portfolio_id);
            """
        )

        # Region targets table (mirrors sector targets structure).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_region_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER NOT NULL,
                region_name TEXT NOT NULL,
                target_pct REAL NOT NULL,
                min_pct REAL NOT NULL,
                max_pct REAL NOT NULL,
                FOREIGN KEY (portfolio_id) REFERENCES portfolios(id) ON DELETE CASCADE,
                UNIQUE(portfolio_id, region_name)
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_region_targets_portfolio
            ON portfolio_region_targets(portfolio_id);
            """
        )

        # Stamp schema touch
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cur.execute(
            """
            UPDATE portfolio_policy
            SET updated_at = COALESCE(updated_at, ?)
            WHERE updated_at IS NULL;
            """,
            (now,),
        )

        con.commit()
