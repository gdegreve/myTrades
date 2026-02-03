from __future__ import annotations
import dash_bootstrap_components as dbc
import threading
import json
import plotly.graph_objects as go

from dash import dcc, html, Input, Output, State, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate

from app.db.portfolio_repo import list_portfolios
from app.db.policy_repo import load_policy_snapshot
from app.db.ledger_repo import list_trades, list_cash_movements, get_ticker_sectors, get_ticker_regions
from app.db.rebalance_repo import (
    get_ai_settings,
    get_cached_ai_job,
    create_ai_job,
    update_ai_job,
    get_signals_for_portfolio,
)
from app.db.strategy_repo import get_assignment_map, get_saved_strategy_by_id
from app.domain.ledger import compute_positions, compute_cash_balance
from app.domain.rebalance import compute_full_rebalance_plan
from app.services.market_data import get_latest_daily_closes_cached
from app.services.signal_sizing_service import build_signal_trade_targets


def _safe_float(value, default=0.0):
    """Safely convert value to float, handling strings, None, and invalid values."""
    if value is None or value == "" or value == "N/A":
        return default
    try:
        # If it's already a float/int, return it
        if isinstance(value, (int, float)):
            return float(value)
        # If it's a string, strip common formatting
        if isinstance(value, str):
            cleaned = value.replace("€", "").replace(",", "").replace("%", "").strip()
            return float(cleaned) if cleaned else default
        return float(value)
    except (ValueError, TypeError):
        return default


def _run_ai_review_background(job_id: int, trades_data: list, ai_settings: dict):
    """Background worker that calls Ollama API and updates job status.

    This runs in a separate thread to avoid blocking the Dash callback.
    """
    from app.db.rebalance_repo import update_ai_job

    try:
        update_ai_job(job_id, "running")

        base_url = ai_settings.get("base_url", "http://localhost:11434")
        model = ai_settings.get("model", "llama3.1:8b")
        timeout_ms = ai_settings.get("timeout_ms", 30000)

        # Build compact prompt
        trade_summary = []
        for trade in (trades_data or [])[:10]:  # Limit to top 10 trades
            # Safely parse estimated_eur (may be formatted string like "123.45")
            est_eur = _safe_float(trade.get('estimated_eur', 0))
            trade_summary.append(
                f"- {trade.get('layer', 'Signal')}: {trade.get('signal', 'HOLD')} "
                f"{trade.get('ticker', '?')} ({trade.get('shares_delta', 0)} shares, "
                f"€{est_eur:.0f})"
            )

        prompt = f"""Analyze this rebalance plan in plain English (200 words max):

Trades:
{chr(10).join(trade_summary) if trade_summary else "No trades proposed."}

Explain:
1. What changes and why
2. Risk of NOT rebalancing
3. New risks introduced
4. Sensitivity to macro uncertainty (tariffs, rates, volatility)

Keep it simple, no financial advice."""

        # Call Ollama API
        import urllib.request
        import urllib.error

        url = f"{base_url}/api/generate"
        data = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout_ms / 1000) as response:
                result = json.loads(response.read().decode("utf-8"))
                ai_text = result.get("response", "No response from model.")
                update_ai_job(job_id, "completed", ai_text)
        except urllib.error.URLError as e:
            update_ai_job(job_id, "failed", f"Connection error: {str(e)}")
        except Exception as e:
            update_ai_job(job_id, "failed", f"API error: {str(e)}")

    except Exception as e:
        try:
            update_ai_job(job_id, "failed", f"Worker error: {str(e)}")
        except Exception:
            pass  # If we can't even update the job, just log and exit


# Pill styling constants
PILL_ACTIVE_STYLE = {
    "backgroundColor": "var(--accent)",
    "color": "white",
    "border": "1px solid var(--accent)",
}

PILL_INACTIVE_STYLE = {
    "backgroundColor": "transparent",
    "color": "var(--text)",
    "border": "1px solid var(--border-strong)",
}


def layout() -> html.Div:
    return html.Div(
        children=[
            # Page header with portfolio selector
            html.Div(
                className="page-header",
                children=[
                    html.Div(
                        children=[
                            html.H2("Portfolio – Rebalance", style={"margin": "0"}),
                            html.Div(
                                "Convert signals into a rebalance plan.",
                                className="page-subtitle",
                            ),
                        ]
                    ),
                    html.Div(
                        className="page-header-actions",
                        children=[
                            html.Div(
                                children=[
                                    html.Div("Portfolio", className="field-label"),
                                    dcc.Dropdown(
                                        id="rebalance-portfolio",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        style={"minWidth": "220px"},
                                    ),
                                ]
                            ),
                        ],
                    ),
                ],
            ),

            html.Hr(style={"margin": "16px 0"}),

            # Status bar
            html.Div(
                id="rebalance-status-bar",
                style={"marginBottom": "14px"},
            ),

            # Nav pills for tab navigation
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    dbc.Nav(
                        pills=True,
                        className="segmented-pills",
                        children=[
                            dbc.NavLink(
                                "Plan",
                                id="rebalance-nav-plan",
                                active=True,
                                style=PILL_ACTIVE_STYLE,
                            ),
                            dbc.NavLink(
                                "Compare",
                                id="rebalance-nav-compare",
                                active=False,
                                style=PILL_INACTIVE_STYLE,
                            ),
                        ],
                    ),
                ],
            ),

            # =================================================================
            # PANEL 1: Plan (visible by default)
            # =================================================================
            html.Div(
                id="rebalance-panel-plan",
                style={"display": "block"},
                children=[
                    # Summary cards
                    html.Div(
                        className="grid-3",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Sector Breaches", className="card-title"),
                                    html.Div(
                                        id="rebalance-summary-sector-breaches",
                                        children="0",
                                        style={"fontSize": "28px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Region Breaches", className="card-title"),
                                    html.Div(
                                        id="rebalance-summary-region-breaches",
                                        children="0",
                                        style={"fontSize": "28px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Cash Status", className="card-title"),
                                    html.Div(
                                        id="rebalance-summary-cash-status",
                                        children="OK",
                                        style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                ],
                            ),
                        ],
                    ),

                    # Mode toggle card
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                                children=[
                                    html.Div("Rebalance Mode", className="card-title"),
                                    dbc.RadioItems(
                                        id="rebalance-mode-toggle",
                                        options=[
                                            {"label": "Signals only", "value": "signals_only"},
                                            {"label": "Signals + Rebalance", "value": "full"},
                                        ],
                                        value="signals_only",
                                        inline=True,
                                    ),
                                ],
                            ),
                        ],
                    ),

                    # Drift table
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"},
                                children=[
                                    html.Div("Policy Drift", className="card-title"),
                                    dcc.Dropdown(
                                        id="rebalance-drift-sort",
                                        options=[
                                            {"label": "Status (Worst First)", "value": "status"},
                                            {"label": "Drift (Largest)", "value": "drift"},
                                            {"label": "Dimension", "value": "dimension"},
                                        ],
                                        value="status",
                                        clearable=False,
                                        className="dd-blend",
                                        style={"minWidth": "180px"},
                                    ),
                                ],
                            ),
                            DataTable(
                                id="rebalance-drift-table",
                                columns=[
                                    {"name": "Dimension", "id": "dimension"},
                                    {"name": "Bucket", "id": "bucket"},
                                    {"name": "Target %", "id": "target_pct", "type": "numeric"},
                                    {"name": "Current %", "id": "current_pct", "type": "numeric"},
                                    {"name": "Drift %", "id": "drift_pct", "type": "numeric"},
                                    {"name": "Status", "id": "status"},
                                    {"name": "Action", "id": "action"},
                                ],
                                data=[],
                                page_action='none',
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),

                    # Suggested trades table
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"},
                                children=[
                                    html.Div("Suggested Trades", className="card-title"),
                                    dcc.Dropdown(
                                        id="rebalance-trades-sort",
                                        options=[
                                            {"label": "Layer", "value": "layer"},
                                            {"label": "Est. EUR (Largest)", "value": "eur"},
                                            {"label": "Ticker", "value": "ticker"},
                                        ],
                                        value="layer",
                                        clearable=False,
                                        className="dd-blend",
                                        style={"minWidth": "180px"},
                                    ),
                                ],
                            ),
                            DataTable(
                                id="rebalance-trades-table",
                                columns=[
                                    {"name": "Layer", "id": "layer"},
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Sector", "id": "sector"},
                                    {"name": "Region", "id": "region"},
                                    {"name": "Signal", "id": "signal"},
                                    {"name": "Shares Δ", "id": "shares_delta", "type": "numeric"},
                                    {"name": "Price", "id": "price", "type": "numeric"},
                                    {"name": "Est. EUR", "id": "estimated_eur", "type": "numeric"},
                                    {"name": "Stop", "id": "stop_price", "type": "numeric"},
                                    {"name": "Limit", "id": "limit_price", "type": "numeric"},
                                    {"name": "Reason", "id": "reason"},
                                ],
                                data=[],
                                page_action='none',
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),

                    # Cash preview card
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Cash Preview", className="card-title", style={"marginBottom": "10px"}),
                            html.Div(id="rebalance-cash-preview"),
                        ],
                    ),
                ],
            ),

            # =================================================================
            # PANEL 2: Compare (hidden by default)
            # =================================================================
            html.Div(
                id="rebalance-panel-compare",
                style={"display": "none"},
                children=[
                    # AI Review card (full width at top)
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "10px"},
                                children=[
                                    html.Div("AI Review", className="card-title"),
                                    html.Div(
                                        children=[
                                            dbc.Badge(
                                                "Not started",
                                                id="rebalance-ai-status",
                                                color="secondary",
                                                style={"marginRight": "10px"},
                                            ),
                                            html.Button(
                                                "Run AI review",
                                                id="rebalance-ai-run-btn",
                                                className="btn-primary",
                                                n_clicks=0,
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(id="rebalance-ai-meta", className="hint-text", style={"marginBottom": "10px"}),
                            html.Div(
                                id="rebalance-ai-output",
                                style={"minHeight": "100px", "padding": "10px", "backgroundColor": "rgba(0,0,0,0.2)", "borderRadius": "4px"},
                            ),
                            dcc.Store(id="rebalance-ai-job"),
                            dcc.Interval(id="rebalance-ai-poll", interval=1500, disabled=True),
                        ],
                    ),

                    # Before/After allocation graphs
                    html.Div(
                        className="grid-2",
                        style={"marginBottom": "14px"},
                        children=[
                            # Left: Before Allocation (Sector)
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Before Allocation (Sector)", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="rebalance-before-sector", config={"displayModeBar": False}),
                                ],
                            ),
                            # Right: After Allocation (Sector)
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("After Allocation (Sector)", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="rebalance-after-sector", config={"displayModeBar": False}),
                                ],
                            ),
                        ],
                    ),

                    # Two-column comparison
                    html.Div(
                        className="grid-2",
                        children=[
                            # Left: Current State
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Current State", className="card-title", style={"marginBottom": "10px"}),
                                    html.Div(id="rebalance-current-state"),
                                ],
                            ),
                            # Right: Proposed State
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Proposed State", className="card-title", style={"marginBottom": "10px"}),
                                    html.Div(id="rebalance-proposed-state"),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
        style={"maxWidth": "1100px"},
    )


@callback(
    Output("rebalance-portfolio", "options"),
    Output("rebalance-portfolio", "value"),
    Input("url", "pathname"),
)
def populate_portfolio_dropdown(pathname):
    """Populate portfolio dropdown on page load."""
    if pathname != "/portfolio/rebalance":
        raise PreventUpdate
    portfolios = list_portfolios()
    if not portfolios:
        return [], None
    options = [{"label": p["name"], "value": p["id"]} for p in portfolios]
    return options, portfolios[0]["id"]


@callback(
    Output("rebalance-panel-plan", "style"),
    Output("rebalance-panel-compare", "style"),
    Output("rebalance-nav-plan", "active"),
    Output("rebalance-nav-compare", "active"),
    Output("rebalance-nav-plan", "style"),
    Output("rebalance-nav-compare", "style"),
    Input("rebalance-nav-plan", "n_clicks"),
    Input("rebalance-nav-compare", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_rebalance_panels(plan_clicks, compare_clicks):
    """Toggle between Plan and Compare panels based on pill clicks."""
    from dash import ctx

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Default: all hidden, all inactive
    panel_styles = {
        "plan": {"display": "none"},
        "compare": {"display": "none"},
    }
    active_states = {
        "plan": False,
        "compare": False,
    }
    pill_styles = {
        "plan": PILL_INACTIVE_STYLE,
        "compare": PILL_INACTIVE_STYLE,
    }

    # Determine which tab was clicked
    if button_id == "rebalance-nav-plan":
        panel_styles["plan"] = {"display": "block"}
        active_states["plan"] = True
        pill_styles["plan"] = PILL_ACTIVE_STYLE
    elif button_id == "rebalance-nav-compare":
        panel_styles["compare"] = {"display": "block"}
        active_states["compare"] = True
        pill_styles["compare"] = PILL_ACTIVE_STYLE
    else:
        raise PreventUpdate

    return (
        panel_styles["plan"],
        panel_styles["compare"],
        active_states["plan"],
        active_states["compare"],
        pill_styles["plan"],
        pill_styles["compare"],
    )


@callback(
    Output("rebalance-drift-table", "data"),
    Output("rebalance-trades-table", "data"),
    Output("rebalance-summary-sector-breaches", "children"),
    Output("rebalance-summary-region-breaches", "children"),
    Output("rebalance-summary-cash-status", "children"),
    Output("rebalance-cash-preview", "children"),
    Output("rebalance-current-state", "children"),
    Output("rebalance-proposed-state", "children"),
    Output("rebalance-status-bar", "children"),
    Input("rebalance-portfolio", "value"),
    Input("rebalance-mode-toggle", "value"),
)
def load_rebalance_data(portfolio_id, mode):
    """Load and compute rebalance plan data.

    This is the main data-loading callback for the rebalance page.
    It orchestrates calls to the domain layer to compute the full rebalance plan.
    Now with signal sizing policy integration.
    """
    if portfolio_id is None:
        raise PreventUpdate

    # Load holdings via ledger
    trades = list_trades(portfolio_id, limit=1000)
    cash_movements = list_cash_movements(portfolio_id, limit=1000)
    ticker_sectors = get_ticker_sectors(portfolio_id)
    ticker_regions = get_ticker_regions(portfolio_id)

    # Compute positions and cash
    positions = compute_positions(trades)
    cash_balance = compute_cash_balance(cash_movements, trades)

    # Load policy
    policy_snapshot = load_policy_snapshot(portfolio_id)
    policy = policy_snapshot.get("policy", {})

    # Load signals
    signals_list = get_signals_for_portfolio(portfolio_id)

    # Convert signals list to dict format for signal sizing service
    signals_dict = {}
    for sig in signals_list:
        ticker = sig["ticker"]
        signals_dict[ticker] = {
            "signal": sig.get("signal", "HOLD"),
            "strength": 1,  # Default, could be parsed from meta_json
            "confidence": 1.0,
            "reason": sig.get("reason", ""),
        }

    # Get latest prices
    position_tickers = [p["ticker"] for p in positions]
    signal_tickers = [s["ticker"] for s in signals_list]
    all_tickers = list(set(position_tickers + signal_tickers))

    prices, missing_tickers = get_latest_daily_closes_cached(
        all_tickers,
        max_age_minutes=60,
        force_refresh=False,
    )

    # Build ticker metadata
    ticker_metadata = {}
    for ticker in all_tickers:
        ticker_metadata[ticker] = {
            "sector": ticker_sectors.get(ticker, "Unknown"),
            "region": ticker_regions.get(ticker, "Unknown"),
        }

    # Check if signal sizing is enabled
    signal_sizing_mode = policy.get("signal_sizing_mode", "off")

    # If signal sizing is enabled, use signal sizing service instead of old compute_signal_trades
    if signal_sizing_mode != "off":
        # Load strategy assignments
        assignment_map = get_assignment_map(portfolio_id)

        # Build saved strategy map
        saved_strategy_map = {}
        for ticker, saved_strategy_id in assignment_map.items():
            strategy = get_saved_strategy_by_id(portfolio_id, saved_strategy_id)
            if strategy:
                saved_strategy_map[saved_strategy_id] = strategy

        # Compute NAV
        nav_eur = cash_balance
        for pos in positions:
            price = prices.get(pos["ticker"], pos.get("avg_cost", 0.0))
            nav_eur += pos["shares"] * price

        # Build holdings rows for signal sizing service
        holdings_rows = []
        for pos in positions:
            price = prices.get(pos["ticker"], pos.get("avg_cost", 0.0))
            value = pos["shares"] * price
            holdings_rows.append({
                "ticker": pos["ticker"],
                "shares": pos["shares"],
                "value": value,
            })

        # Call signal sizing service
        signal_trade_targets = build_signal_trade_targets(
            portfolio_id=portfolio_id,
            holdings_rows=holdings_rows,
            nav_eur=nav_eur,
            prices=prices,
            signals=signals_dict,
            assignment_map=assignment_map,
            saved_strategy_map=saved_strategy_map,
            policy=policy,
            ohlcv_data=None,  # TODO: Optionally load OHLCV for ATR calculation
        )

        # Convert signal sizing trades to plan format
        signal_trades = []
        for trade in signal_trade_targets:
            price = prices.get(trade["ticker"], 0.0)

            # Include both active and skipped trades (so user can see why trades are skipped)
            if trade.get("skipped", False):
                # Show skipped trade with reason
                signal_trades.append({
                    "ticker": trade["ticker"],
                    "layer": "Skipped",
                    "signal": trade.get("signal", "HOLD"),
                    "shares_delta": 0,
                    "price": price,
                    "estimated_eur": 0.0,
                    "reason": f"⚠️ {trade.get('reason', 'Skipped')}",
                    "stop_price": None,
                    "limit_price": None,
                })
            elif trade.get("delta_shares", 0) != 0:
                # Active trade
                signal_trades.append({
                    "ticker": trade["ticker"],
                    "layer": "Signal",
                    "signal": trade.get("signal", "HOLD"),
                    "shares_delta": trade["delta_shares"],
                    "price": price,
                    "estimated_eur": trade.get("delta_value_eur", 0.0),
                    "reason": trade.get("reason", ""),
                    "stop_price": trade.get("stop_price"),
                    "limit_price": trade.get("limit_price"),
                })

        # Use modified compute_full_rebalance_plan with our signal trades
        # For now, we'll use the standard plan but replace signal_trades
        plan = compute_full_rebalance_plan(
            positions=positions,
            cash=cash_balance,
            policy_snapshot=policy_snapshot,
            signals=signals_list,
            prices=prices,
            ticker_metadata=ticker_metadata,
        )

        # Replace signal trades with our sizing-based trades
        plan["signal_trades"] = signal_trades
        plan["all_trades"] = signal_trades + plan["compensation_trades"]

    else:
        # Use standard rebalance plan
        plan = compute_full_rebalance_plan(
            positions=positions,
            cash=cash_balance,
            policy_snapshot=policy_snapshot,
            signals=signals_list,
            prices=prices,
            ticker_metadata=ticker_metadata,
        )

    # Determine which trades to display based on mode
    if mode == "signals_only":
        trades_to_display = plan["signal_trades"]
        cash_preview_data = plan["cash_preview_signals_only"]
        drift_data = plan["drift_before"]
    else:  # "full"
        trades_to_display = plan["all_trades"]
        cash_preview_data = plan["cash_preview_full"]
        drift_data = plan["drift_after"]

    # Format drift table
    drift_table_data = []
    for drift in drift_data:
        drift_table_data.append({
            "dimension": drift.get("dimension", "Unknown"),
            "bucket": drift["bucket"],
            "target_pct": f"{drift['target_pct']:.1f}",
            "current_pct": f"{drift['current_pct']:.1f}",
            "drift_pct": f"{drift['drift_pct']:+.1f}",
            "status": drift["status"],
            "action": drift["action"],
        })

    # Format trades table
    trades_table_data = []
    for trade in trades_to_display:
        ticker = trade["ticker"]
        meta = ticker_metadata.get(ticker, {})

        # Format stop/limit prices
        stop_price_str = f"{trade['stop_price']:.2f}" if trade.get("stop_price") else "-"
        limit_price_str = f"{trade['limit_price']:.2f}" if trade.get("limit_price") else "-"

        trades_table_data.append({
            "layer": trade["layer"],
            "ticker": ticker,
            "sector": meta.get("sector", "Unknown"),
            "region": meta.get("region", "Unknown"),
            "signal": trade["signal"],
            "shares_delta": trade["shares_delta"],
            "price": f"{trade['price']:.2f}",
            "estimated_eur": f"{trade['estimated_eur']:.2f}",
            "stop_price": stop_price_str,
            "limit_price": limit_price_str,
            "reason": trade["reason"],
        })

    # Summary cards
    summary = plan["summary"]
    sector_breaches = summary["sector_breaches"]
    region_breaches = summary["region_breaches"]
    cash_status = summary["cash_status"]

    # Cash preview
    cash_preview = html.Div(
        children=[
            html.Div(f"Starting cash: €{cash_preview_data['starting_cash']:,.2f}", className="cash-preview-text"),
            html.Div(f"Net impact: €{cash_preview_data['net_impact']:,.2f}", className="cash-preview-text"),
            html.Div(f"Ending cash: €{cash_preview_data['ending_cash']:,.2f}", className="cash-preview-text"),
            html.Div(
                f"Ending %: {cash_preview_data['ending_cash_pct']:.1f}%" if cash_preview_data['ending_cash_pct'] is not None else "N/A",
                className="cash-preview-text"
            ),
            dbc.Badge(
                cash_preview_data["status"] or "Unknown",
                color="success" if cash_preview_data["status"] == "OK" else ("warning" if cash_preview_data["status"] == "WARN" else "danger"),
                style={"marginTop": "4px"},
            ),
        ]
    )

    # Current state summary
    current_state = html.Div(
        children=[
            html.Div(f"Cash: €{cash_balance:,.2f}", style={"marginBottom": "6px"}),
            html.Div(f"Positions: {len(positions)}", style={"marginBottom": "6px"}),
            html.Div(f"Signals: {len(signals_list)}", style={"marginBottom": "6px"}),
        ]
    )

    # Proposed state summary (after trades)
    proposed_cash = cash_preview_data["ending_cash"]
    proposed_positions = len(set([t["ticker"] for t in trades_to_display if t["shares_delta"] > 0]) | set([p["ticker"] for p in positions]))
    proposed_state = html.Div(
        children=[
            html.Div(f"Cash: €{proposed_cash:,.2f}", style={"marginBottom": "6px"}),
            html.Div(f"Estimated positions: {proposed_positions}", style={"marginBottom": "6px"}),
            html.Div(f"Total trades: {len(trades_to_display)}", style={"marginBottom": "6px"}),
        ]
    )

    # Status bar
    status_msg = f"Loaded {len(signals_list)} signals, {len(trades_to_display)} trades planned"
    if signal_sizing_mode != "off":
        status_msg += f" | Signal sizing: {signal_sizing_mode}"
    if missing_tickers:
        status_msg += f" | {len(missing_tickers)} tickers missing prices"

    return (
        drift_table_data,
        trades_table_data,
        str(sector_breaches),
        str(region_breaches),
        cash_status,
        cash_preview,
        current_state,
        proposed_state,
        status_msg,
    )


@callback(
    Output("rebalance-drift-table", "data", allow_duplicate=True),
    Output("rebalance-trades-table", "data", allow_duplicate=True),
    Input("rebalance-drift-sort", "value"),
    Input("rebalance-trades-sort", "value"),
    State("rebalance-drift-table", "data"),
    State("rebalance-trades-table", "data"),
    prevent_initial_call=True,
)
def sort_rebalance_tables(drift_sort, trades_sort, drift_data, trades_data):
    """Sort drift and trades tables based on dropdown selections."""
    from dash import ctx

    if not ctx.triggered or not drift_data or not trades_data:
        raise PreventUpdate

    # Sort drift table
    sorted_drift = drift_data.copy()
    if drift_sort == "status":
        # Status priority: BREACH > WARN > OK
        status_order = {"BREACH": 0, "WARN": 1, "OK": 2}
        sorted_drift.sort(key=lambda x: (
            status_order.get(x.get("status", "OK"), 99),
            -abs(_safe_float(x.get("drift_pct", "0")))
        ))
    elif drift_sort == "drift":
        # Sort by absolute drift value descending
        sorted_drift.sort(key=lambda x: -abs(_safe_float(x.get("drift_pct", "0"))))
    elif drift_sort == "dimension":
        # Sort alphabetically by dimension + bucket
        sorted_drift.sort(key=lambda x: (x.get("dimension", ""), x.get("bucket", "")))

    # Sort trades table
    sorted_trades = trades_data.copy()
    if trades_sort == "layer":
        # Layer priority: Signal > Rebalance
        layer_order = {"Signal": 0, "Rebalance": 1}
        sorted_trades.sort(key=lambda x: (
            layer_order.get(x.get("layer", "Signal"), 99),
            x.get("ticker", "")
        ))
    elif trades_sort == "eur":
        # Sort by absolute EUR value descending
        sorted_trades.sort(key=lambda x: -abs(_safe_float(x.get("estimated_eur", "0"))))
    elif trades_sort == "ticker":
        # Sort alphabetically by ticker
        sorted_trades.sort(key=lambda x: x.get("ticker", ""))

    return sorted_drift, sorted_trades


@callback(
    Output("rebalance-ai-status", "children"),
    Output("rebalance-ai-job", "data"),
    Output("rebalance-ai-poll", "disabled"),
    Input("rebalance-ai-run-btn", "n_clicks"),
    State("rebalance-portfolio", "value"),
    State("rebalance-trades-table", "data"),
    prevent_initial_call=True,
)
def start_ai_review(n_clicks, portfolio_id, trades_data):
    """Start an AI review job for the rebalance plan."""
    if n_clicks == 0 or portfolio_id is None:
        raise PreventUpdate

    # Get AI settings
    ai_settings = get_ai_settings(portfolio_id)
    if not ai_settings.get("enabled"):
        return "AI review disabled", None, True

    # Create job stub (actual AI call would happen in background/service layer)
    import hashlib
    from datetime import date

    plan_hash = hashlib.md5(str(trades_data).encode()).hexdigest()[:8]
    eod_date = date.today().isoformat()
    model = ai_settings.get("model", "llama3.1:8b")

    # Check for cached job
    cached_job = get_cached_ai_job(portfolio_id, eod_date, plan_hash, model)
    if cached_job and cached_job["status"] == "completed":
        return "Completed (cached)", {"job_id": cached_job["id"]}, True

    # Create new job
    job_id = create_ai_job(portfolio_id, eod_date, plan_hash, model)

    # Spawn background worker thread to call Ollama
    worker_thread = threading.Thread(
        target=_run_ai_review_background,
        args=(job_id, trades_data, ai_settings),
        daemon=True,
    )
    worker_thread.start()

    return "Running...", {"job_id": job_id}, False


@callback(
    Output("rebalance-ai-output", "children"),
    Output("rebalance-ai-meta", "children"),
    Output("rebalance-ai-status", "children", allow_duplicate=True),
    Output("rebalance-ai-poll", "disabled", allow_duplicate=True),
    Input("rebalance-ai-poll", "n_intervals"),
    State("rebalance-ai-job", "data"),
    prevent_initial_call=True,
)
def poll_ai_job(n_intervals, job_data):
    """Poll AI job status and display results when ready."""
    if job_data is None or "job_id" not in job_data:
        raise PreventUpdate

    from app.db.rebalance_repo import get_ai_job_by_id

    job = get_ai_job_by_id(job_data["job_id"])
    if not job:
        return "Job not found", "", "Error", True

    status = job["status"]

    if status == "completed":
        result = job.get("result", "No output")
        meta = f"Completed at {job['completed_at']}"
        return dcc.Markdown(result), meta, "Completed", True

    elif status == "failed":
        result = job.get("result", "Unknown error")
        meta = f"Failed at {job['completed_at']}"
        return result, meta, "Failed", True

    elif status == "running":
        return "AI review in progress...", f"Started at {job['created_at']}", "Running", False

    else:  # pending
        return "Waiting to start...", f"Created at {job['created_at']}", "Pending", False


@callback(
    Output("rebalance-before-sector", "figure"),
    Output("rebalance-after-sector", "figure"),
    Input("rebalance-portfolio", "value"),
    Input("rebalance-mode-toggle", "value"),
)
def update_allocation_graphs(portfolio_id, mode):
    """Update Before/After allocation graphs on Compare tab."""
    if portfolio_id is None:
        # Return empty charts
        empty_fig = go.Figure()
        empty_fig.add_annotation(
            text="Select a portfolio to view allocations",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="rgba(255,255,255,0.5)"),
        )
        empty_fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            height=300,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        return empty_fig, empty_fig

    # Load data (same logic as load_rebalance_data)
    trades = list_trades(portfolio_id, limit=1000)
    cash_movements = list_cash_movements(portfolio_id, limit=1000)
    ticker_sectors = get_ticker_sectors(portfolio_id)
    ticker_regions = get_ticker_regions(portfolio_id)

    positions = compute_positions(trades)
    cash_balance = compute_cash_balance(cash_movements, trades)
    policy_snapshot = load_policy_snapshot(portfolio_id)
    signals = get_signals_for_portfolio(portfolio_id)

    position_tickers = [p["ticker"] for p in positions]
    signal_tickers = [s["ticker"] for s in signals]
    all_tickers = list(set(position_tickers + signal_tickers))

    prices, _ = get_latest_daily_closes_cached(all_tickers, max_age_minutes=60, force_refresh=False)

    ticker_metadata = {}
    for ticker in all_tickers:
        ticker_metadata[ticker] = {
            "sector": ticker_sectors.get(ticker, "Unknown"),
            "region": ticker_regions.get(ticker, "Unknown"),
        }

    # Compute rebalance plan
    plan = compute_full_rebalance_plan(
        positions=positions,
        cash=cash_balance,
        policy_snapshot=policy_snapshot,
        signals=signals,
        prices=prices,
        ticker_metadata=ticker_metadata,
    )

    # Get before/after sector allocations
    # Before = current allocations
    sector_values_before = {}
    total_value_before = cash_balance
    for pos in positions:
        ticker = pos["ticker"]
        price = prices.get(ticker, pos["avg_cost"])
        value = pos["shares"] * price
        total_value_before += value
        sector = ticker_metadata.get(ticker, {}).get("sector", "Unknown")
        sector_values_before[sector] = sector_values_before.get(sector, 0.0) + value

    # Convert to percentages
    sector_alloc_before = {}
    if total_value_before > 0:
        sector_alloc_before = {
            s: (v / total_value_before) * 100.0
            for s, v in sector_values_before.items()
        }

    # After = depends on mode
    if mode == "signals_only":
        # After signal trades only
        final_state = plan.get("post_signal_state", {})
    else:
        # After all trades (signals + rebalance)
        final_state = plan.get("final_state", {})

    sector_alloc_after = final_state.get("sector_allocations", {}) if final_state else sector_alloc_before

    # Build Before chart
    sectors_before = sorted(sector_alloc_before.items(), key=lambda x: -x[1])[:10]
    before_fig = go.Figure()
    before_fig.add_trace(go.Bar(
        x=[pct for _, pct in sectors_before],
        y=[sector for sector, _ in sectors_before],
        orientation='h',
        marker=dict(color="#2D7DFF"),
    ))
    before_fig.update_layout(
        margin=dict(l=100, r=10, t=10, b=40),
        height=300,
        xaxis_title="Allocation (%)",
        yaxis=dict(autorange="reversed"),
        showlegend=False,
        font=dict(color="rgba(255,255,255,0.9)", size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    before_fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(255,255,255,0.1)",
        tickfont=dict(color="rgba(255,255,255,0.8)"),
        title_font=dict(color="rgba(255,255,255,0.8)")
    )
    before_fig.update_yaxes(
        showgrid=False,
        tickfont=dict(color="rgba(255,255,255,0.8)")
    )

    # Build After chart
    sectors_after = sorted(sector_alloc_after.items(), key=lambda x: -x[1])[:10]
    after_fig = go.Figure()
    after_fig.add_trace(go.Bar(
        x=[pct for _, pct in sectors_after],
        y=[sector for sector, _ in sectors_after],
        orientation='h',
        marker=dict(color="#32C5FF"),
    ))
    after_fig.update_layout(
        margin=dict(l=100, r=10, t=10, b=40),
        height=300,
        xaxis_title="Allocation (%)",
        yaxis=dict(autorange="reversed"),
        showlegend=False,
        font=dict(color="rgba(255,255,255,0.9)", size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    after_fig.update_xaxes(
        showgrid=True,
        gridcolor="rgba(255,255,255,0.1)",
        tickfont=dict(color="rgba(255,255,255,0.8)"),
        title_font=dict(color="rgba(255,255,255,0.8)")
    )
    after_fig.update_yaxes(
        showgrid=False,
        tickfont=dict(color="rgba(255,255,255,0.8)")
    )

    return before_fig, after_fig
