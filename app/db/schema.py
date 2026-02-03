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

                signal_sizing_mode TEXT DEFAULT 'off',
                signal_step_pct REAL DEFAULT 1.0,
                signal_strong_step_pct REAL DEFAULT 2.0,
                signal_exit_threshold_pct REAL DEFAULT 0.5,
                signal_min_trade_eur REAL DEFAULT 250.0,
                signal_risk_per_trade_pct REAL DEFAULT 0.5,
                signal_atr_period INTEGER DEFAULT 14,
                signal_atr_mult REAL DEFAULT 2.0,
                signal_stop_source TEXT DEFAULT 'strategy_stop',
                signal_stop_order_type TEXT DEFAULT 'stop_limit',
                signal_stop_limit_buffer_bps REAL DEFAULT 25.0,

                updated_at TEXT
            );
            """
        )

        # Add signal sizing columns to portfolio_policy (idempotent via try/except)
        signal_sizing_columns = [
            ("signal_sizing_mode", "TEXT DEFAULT 'off'"),
            ("signal_step_pct", "REAL DEFAULT 1.0"),
            ("signal_strong_step_pct", "REAL DEFAULT 2.0"),
            ("signal_exit_threshold_pct", "REAL DEFAULT 0.5"),
            ("signal_min_trade_eur", "REAL DEFAULT 250.0"),
            ("signal_risk_per_trade_pct", "REAL DEFAULT 0.5"),
            ("signal_atr_period", "INTEGER DEFAULT 14"),
            ("signal_atr_mult", "REAL DEFAULT 2.0"),
            ("signal_stop_source", "TEXT DEFAULT 'strategy_stop'"),
            ("signal_stop_order_type", "TEXT DEFAULT 'stop_limit'"),
            ("signal_stop_limit_buffer_bps", "REAL DEFAULT 25.0"),
        ]

        for col_name, col_def in signal_sizing_columns:
            try:
                cur.execute(f"ALTER TABLE portfolio_policy ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass  # Column already exists

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

        # Price bars table for yfinance cache (daily close prices).
        # Expandable for timeseries/drift analysis later.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS price_bars (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL DEFAULT '1d',
                date TEXT NOT NULL,
                close REAL NOT NULL,
                currency TEXT DEFAULT 'EUR',
                provider TEXT DEFAULT 'yfinance',
                fetched_at TEXT NOT NULL,
                UNIQUE(symbol, interval, date)
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_price_bars_symbol_interval
            ON price_bars(symbol, interval);
            """
        )

        # Strategy definitions table (signal generation strategies)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_definitions (
                strategy_key TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                params_json TEXT,
                updated_at TEXT
            );
            """
        )

        # Ticker-to-strategy mapping (which strategy applies to which ticker)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ticker_strategy_map (
                portfolio_id INTEGER,
                ticker TEXT,
                strategy_key TEXT,
                updated_at TEXT,
                PRIMARY KEY (portfolio_id, ticker)
            );
            """
        )

        # Signals backlog (historical signals for review)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS signals_backlog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER,
                ts TEXT,
                ticker TEXT,
                strategy_key TEXT,
                signal TEXT,
                reason TEXT,
                meta_json TEXT
            );
            """
        )

        # Benchmarks table (for Portfolio Overview comparisons)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmarks (
                benchmark_id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                base_currency TEXT NOT NULL DEFAULT 'EUR',
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )

        # Benchmark constituents (tickers and weights)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_tickers (
                benchmark_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                weight REAL,
                added_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (benchmark_id, ticker),
                FOREIGN KEY (benchmark_id) REFERENCES benchmarks(benchmark_id)
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_benchmark_tickers_ticker
            ON benchmark_tickers(ticker);
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_benchmark_tickers_benchmark_id
            ON benchmark_tickers(benchmark_id);
            """
        )

        # Add ticker and region columns to benchmarks (idempotent via try/except)
        try:
            cur.execute("ALTER TABLE benchmarks ADD COLUMN ticker TEXT")
        except Exception:
            pass  # Column already exists

        try:
            cur.execute("ALTER TABLE benchmarks ADD COLUMN region TEXT")
        except Exception:
            pass  # Column already exists

        # Add fundamental metrics columns to benchmark_fundamentals (idempotent)
        # Growth & Cash Flow metrics
        fundamental_columns = [
            "revenue_growth_yoy REAL",
            "eps_growth_yoy REAL",
            "fcf_margin REAL",
            "fcf_growth_yoy REAL",
            "operating_cf_to_net_income REAL",
            # Balance Sheet & Solvency metrics
            "net_debt_to_ebitda REAL",
            "interest_coverage REAL",
            "current_ratio REAL",
            "debt_to_equity REAL",
            "shares_out_growth_yoy REAL",
        ]

        for col_def in fundamental_columns:
            try:
                cur.execute(f"ALTER TABLE benchmark_fundamentals ADD COLUMN {col_def}")
            except Exception:
                pass  # Column already exists

        # Benchmark EOD price cache table
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_eod (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benchmark_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                close REAL NOT NULL,
                UNIQUE(benchmark_id, date),
                FOREIGN KEY (benchmark_id) REFERENCES benchmarks(benchmark_id) ON DELETE CASCADE
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_benchmark_eod_lookup
            ON benchmark_eod(benchmark_id, date);
            """
        )

        # AI settings table (per-portfolio configuration for AI model review)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_settings (
                portfolio_id INTEGER PRIMARY KEY,
                base_url TEXT NOT NULL DEFAULT 'http://localhost:11434',
                model TEXT NOT NULL DEFAULT 'llama3.1:8b',
                enabled INTEGER NOT NULL DEFAULT 1,
                timeout_ms INTEGER NOT NULL DEFAULT 30000,
                updated_at TEXT
            );
            """
        )

        # AI job cache table (stores AI review results with plan hash for caching)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_job_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER NOT NULL,
                eod_date TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                completed_at TEXT,
                UNIQUE(portfolio_id, eod_date, plan_hash, model)
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ai_job_cache_lookup
            ON ai_job_cache(portfolio_id, eod_date, plan_hash, model);
            """
        )

        # Benchmark snapshot runs table (tracks refresh jobs with progress)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_snapshot_runs (
                run_id TEXT PRIMARY KEY,
                benchmark_id INTEGER NOT NULL,
                run_type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                total INTEGER DEFAULT 0,
                processed INTEGER DEFAULT 0,
                succeeded INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                current_ticker TEXT,
                message TEXT,
                FOREIGN KEY (benchmark_id) REFERENCES benchmarks(benchmark_id) ON DELETE CASCADE
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_snapshot_runs_benchmark
            ON benchmark_snapshot_runs(benchmark_id);
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_snapshot_runs_status
            ON benchmark_snapshot_runs(status);
            """
        )

        # Benchmark fundamentals table (stores scored fundamental data per ticker)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS benchmark_fundamentals (
                run_id TEXT NOT NULL,
                benchmark_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                sector TEXT,
                bench_score_total REAL,
                bench_score_quality REAL,
                bench_score_safety REAL,
                bench_score_value REAL,
                bench_sector_pct_total REAL,
                bench_sector_n INTEGER,
                bench_confidence TEXT,
                fundamental_label TEXT,
                roe REAL,
                operating_margins REAL,
                pe_ttm REAL,
                forward_pe REAL,
                peg REAL,
                ev_to_ebitda REAL,
                price_to_book REAL,
                price_to_sales REAL,
                status TEXT NOT NULL,
                error_message TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, benchmark_id, ticker),
                FOREIGN KEY (benchmark_id) REFERENCES benchmarks(benchmark_id) ON DELETE CASCADE
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_fundamentals_benchmark
            ON benchmark_fundamentals(benchmark_id);
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker
            ON benchmark_fundamentals(ticker);
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_fundamentals_label
            ON benchmark_fundamentals(fundamental_label);
            """
        )

        # Saved strategies table (Phase 3: Backtest strategy persistence)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                name TEXT NOT NULL,
                base_strategy_key TEXT NOT NULL,
                params_json TEXT NOT NULL,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(portfolio_id, ticker, name)
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_saved_strategies_portfolio_ticker
            ON saved_strategies(portfolio_id, ticker);
            """
        )

        # Ticker strategy assignment table (Phase 3: Strategy-to-ticker assignment for signals)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ticker_strategy_assignment (
                portfolio_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                saved_strategy_id INTEGER NOT NULL,
                assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (portfolio_id, ticker),
                FOREIGN KEY(saved_strategy_id) REFERENCES saved_strategies(id) ON DELETE CASCADE
            );
            """
        )

        # Watchlist – tickers the user wants to monitor before buying.
        # A saved strategy can be assigned via ticker_strategy_assignment
        # even though no position exists yet.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                portfolio_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                notes TEXT DEFAULT '',
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (portfolio_id, ticker)
            );
            """
        )

        # Backtest results cache (Phase 4: Cache backtest simulations)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_cache (
                portfolio_id INTEGER NOT NULL DEFAULT 1,
                ticker TEXT NOT NULL,
                strategy_key TEXT NOT NULL,
                params_hash TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (portfolio_id, ticker, strategy_key, params_hash, timeframe)
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_backtest_cache_lookup
            ON backtest_cache(portfolio_id, ticker, strategy_key, params_hash, timeframe);
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
