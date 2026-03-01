from __future__ import annotations
import dash_bootstrap_components as dbc

from dash import dcc, html, Input, Output, State, callback, no_update
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate

from app.db.portfolio_repo import list_portfolios
from app.db.ledger_repo import list_trades, list_cash_movements
from app.db.signals_repo import list_signals_backlog
from app.db.strategy_repo import (
    list_saved_strategies,
    get_saved_strategy_by_id,
    get_assignment_map,
    assign_saved_strategy,
    add_to_watchlist,
    remove_from_watchlist,
    list_watchlist,
)
from app.db.policy_repo import load_policy_snapshot
from app.db.benchmarks_repo import get_latest_fundamentals_for_ticker
from app.services.signal_service import evaluate_position_signal, evaluate_watchlist_signal
from app.services.capital_allocation_service import compute_cas_for_rows
from app.domain.ledger import compute_positions, compute_cash_balance
from app.services.market_data import get_latest_daily_closes_cached


# Pill styling constants (matching Holdings)
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
                            html.H2("Portfolio – Signals", style={"margin": "0"}),
                            html.Div(
                                "Generate and manage trading signals based on strategy assignments.",
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
                                        id="signals-portfolio",
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

            # Status message area
            html.Div(
                id="signals-status",
                style={"marginBottom": "14px"},
            ),

            # Watchlist version counter (triggers overview refresh on add / remove)
            dcc.Store(id="watchlist-version", data=0),

            # Visibility stores for collapsible sections
            dcc.Store(id="signals-hold-visible", data=True),
            dcc.Store(id="signals-risk-visible", data=True),

            # Nav pills for 3 tabs
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    dbc.Nav(
                        pills=True,
                        className="segmented-pills",
                        children=[
                            dbc.NavLink(
                                "Signal overview",
                                id="signals-nav-overview",
                                active=True,
                                style=PILL_ACTIVE_STYLE,
                            ),
                            dbc.NavLink(
                                "Manage strategies",
                                id="signals-nav-manage",
                                active=False,
                                style=PILL_INACTIVE_STYLE,
                            ),
                            dbc.NavLink(
                                "Backlog",
                                id="signals-nav-backlog",
                                active=False,
                                style=PILL_INACTIVE_STYLE,
                            ),
                        ],
                    ),
                ],
            ),

            # =================================================================
            # PANEL 1: Signal overview (visible by default)
            # =================================================================
            html.Div(
                id="signals-panel-overview",
                style={"display": "block"},
                children=[
                    # Today's Allocation Brief
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div("Today's Allocation Brief", className="card-title", style={"marginBottom": "10px"}),
                            html.Div(id="signals-brief", children=[]),
                        ],
                    ),

                    # Priority for Capital
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card-title-row",
                                children=[
                                    html.Div("Priority for Capital", className="card-title"),
                                    html.Div("CAS ≥ 75, non-SELL signals", className="hint-text"),
                                ],
                            ),
                            DataTable(
                                id="signals-priority-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Mode", "id": "mode"},
                                    {"name": "Shares", "id": "shares", "type": "numeric"},
                                    {"name": "Last Price", "id": "last_price"},
                                    {"name": "Signal", "id": "signal"},
                                    {"name": "CAS", "id": "cas", "type": "numeric", "format": {"specifier": ".0f"}},
                                    {"name": "Verdict", "id": "cas_verdict"},
                                    {"name": "Strategy", "id": "strategy"},
                                    {"name": "Reason", "id": "reason"},
                                ],
                                data=[],
                                page_size=10,
                                sort_action="native",
                                sort_mode="single",
                                sort_by=[{"column_id": "cas", "direction": "desc"}],
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                                style_data_conditional=[
                                    {
                                        "if": {"filter_query": "{signal} = BUY"},
                                        "backgroundColor": "rgba(40, 167, 69, 0.15)",
                                        "color": "#2ecc71",
                                    },
                                ],
                            ),
                        ],
                    ),

                    # Hold & Monitor (collapsible)
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card-title-row",
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Hold & Monitor", className="card-title"),
                                            html.Div("CAS 45–74, stable positions", className="hint-text"),
                                        ],
                                    ),
                                    html.Button(
                                        "Show/Hide",
                                        id="signals-hold-toggle-btn",
                                        style={
                                            "fontSize": "12px",
                                            "padding": "4px 10px",
                                            "border": "1px solid var(--border-strong)",
                                            "backgroundColor": "transparent",
                                            "color": "var(--text)",
                                            "borderRadius": "4px",
                                            "cursor": "pointer",
                                        },
                                    ),
                                ],
                            ),
                            html.Div(
                                id="signals-hold-section",
                                children=[
                                    DataTable(
                                        id="signals-hold-table",
                                        columns=[
                                            {"name": "Ticker", "id": "ticker"},
                                            {"name": "Mode", "id": "mode"},
                                            {"name": "Shares", "id": "shares", "type": "numeric"},
                                            {"name": "Last Price", "id": "last_price"},
                                            {"name": "Signal", "id": "signal"},
                                            {"name": "CAS", "id": "cas", "type": "numeric", "format": {"specifier": ".0f"}},
                                            {"name": "Verdict", "id": "cas_verdict"},
                                            {"name": "Strategy", "id": "strategy"},
                                            {"name": "Reason", "id": "reason"},
                                        ],
                                        data=[],
                                        page_size=10,
                                        sort_action="native",
                                        sort_mode="single",
                                        sort_by=[{"column_id": "cas", "direction": "desc"}],
                                        style_table={"overflowX": "auto"},
                                        style_cell={"padding": "10px", "textAlign": "left"},
                                        style_header={"fontWeight": "600"},
                                        style_data_conditional=[
                                            {
                                                "if": {"filter_query": "{signal} = HOLD"},
                                                "backgroundColor": "rgba(243, 156, 18, 0.15)",
                                                "color": "#f39c12",
                                            },
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),

                    # Capital at Risk / Replace (collapsible)
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card-title-row",
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Capital at Risk / Replace", className="card-title"),
                                            html.Div("CAS < 45 or SELL signals", className="hint-text"),
                                        ],
                                    ),
                                    html.Button(
                                        "Show/Hide",
                                        id="signals-risk-toggle-btn",
                                        style={
                                            "fontSize": "12px",
                                            "padding": "4px 10px",
                                            "border": "1px solid var(--border-strong)",
                                            "backgroundColor": "transparent",
                                            "color": "var(--text)",
                                            "borderRadius": "4px",
                                            "cursor": "pointer",
                                        },
                                    ),
                                ],
                            ),
                            html.Div(
                                id="signals-risk-section",
                                children=[
                                    DataTable(
                                        id="signals-risk-table",
                                        columns=[
                                            {"name": "Ticker", "id": "ticker"},
                                            {"name": "Mode", "id": "mode"},
                                            {"name": "Shares", "id": "shares", "type": "numeric"},
                                            {"name": "Last Price", "id": "last_price"},
                                            {"name": "Signal", "id": "signal"},
                                            {"name": "CAS", "id": "cas", "type": "numeric", "format": {"specifier": ".0f"}},
                                            {"name": "Verdict", "id": "cas_verdict"},
                                            {"name": "Strategy", "id": "strategy"},
                                            {"name": "Reason", "id": "reason"},
                                        ],
                                        data=[],
                                        page_size=10,
                                        sort_action="native",
                                        sort_mode="single",
                                        sort_by=[{"column_id": "cas", "direction": "asc"}],
                                        style_table={"overflowX": "auto"},
                                        style_cell={"padding": "10px", "textAlign": "left"},
                                        style_header={"fontWeight": "600"},
                                        style_data_conditional=[
                                            {
                                                "if": {"filter_query": "{signal} = SELL"},
                                                "backgroundColor": "rgba(220, 53, 69, 0.15)",
                                                "color": "#e74c3c",
                                            },
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # =================================================================
            # PANEL 2: Manage strategies (hidden by default)
            # =================================================================
            html.Div(
                id="signals-panel-manage",
                style={"display": "none"},
                children=[
                    # Strategy assignment card
                    html.Div(
                        className="card signals-assign-card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div("Assign Strategy to Ticker", className="card-title", style={"marginBottom": "14px"}),
                            html.Div(
                                className="grid-3",
                                style={"marginBottom": "14px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Ticker", className="field-label"),
                                            dcc.Dropdown(
                                                id="strategy-assign-ticker",
                                                className="dd-blend",
                                                options=[],
                                                placeholder="Select ticker",
                                                clearable=False,
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Strategy", className="field-label"),
                                            dcc.Dropdown(
                                                id="strategy-assign-strategy",
                                                className="dd-blend",
                                                options=[],
                                                placeholder="Select strategy",
                                                clearable=False,
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        style={"display": "flex", "alignItems": "flex-end"},
                                        children=[
                                            html.Button(
                                                "Assign strategy",
                                                id="strategy-assign-btn",
                                                className="btn-primary",
                                                n_clicks=0,
                                                style={"width": "100%"},
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),

                    

                    # Watchlist management card
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div("Watchlist", className="card-title", style={"marginBottom": "14px"}),
                            html.Div(
                                className="grid-3",
                                style={"marginBottom": "14px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Add ticker", className="field-label"),
                                            dcc.Input(
                                                id="watchlist-ticker-input",
                                                type="text",
                                                placeholder="e.g. MSFT",
                                                debounce=False,
                                                style={"width": "100%", "padding": "6px 10px", "borderRadius": "4px", "border": "1px solid var(--border-strong)", "boxSizing": "border-box"},
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Remove ticker", className="field-label"),
                                            dcc.Dropdown(
                                                id="watchlist-remove-ticker",
                                                className="dd-blend",
                                                options=[],
                                                placeholder="Select ticker",
                                                clearable=False,
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        style={"display": "flex", "gap": "8px", "alignItems": "flex-end"},
                                        children=[
                                            html.Button(
                                                "Add",
                                                id="watchlist-add-btn",
                                                className="btn-primary",
                                                n_clicks=0,
                                                style={"flex": "1"},
                                            ),
                                            html.Button(
                                                "Remove",
                                                id="watchlist-remove-btn",
                                                className="btn-secondary",
                                                n_clicks=0,
                                                style={"flex": "1"},
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(id="watchlist-status", style={"marginBottom": "8px"}),
                            DataTable(
                                id="watchlist-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Strategy", "id": "strategy"},
                                    {"name": "Notes", "id": "notes"},
                                    {"name": "Added", "id": "added_at"},
                                ],
                                data=[],
                                page_size=10,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "8px 10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),

                    # Current assignments table
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card-title-row",
                                children=[
                                    html.Div("Current Assignments", className="card-title"),
                                    html.Div("Strategy assignments by ticker", className="hint-text"),
                                ],
                            ),
                            DataTable(
                                id="signals-manage-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Strategy", "id": "strategy"},
                                    {"name": "Status", "id": "status"},
                                ],
                                data=[],
                                page_size=20,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),

                    # Strategy preview card
                    html.Div(
                        className="card",
                        
                        children=[
                            html.Div("Strategy Preview", className="card-title", style={"marginBottom": "10px"}),
                            html.Div(id="strategy-preview-content", children="Select a strategy to view details"),
                        ],
                    ),

                ],
            ),

            # =================================================================
            # PANEL 3: Backlog (hidden by default)
            # =================================================================
            html.Div(
                id="signals-panel-backlog",
                style={"display": "none"},
                children=[
                    # Filters card
                    html.Div(
                        className="card signals-filters-card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div("Filters", className="card-title", style={"marginBottom": "14px"}),
                            html.Div(
                                className="grid-3",
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Ticker", className="field-label"),
                                            dcc.Dropdown(
                                                id="backlog-filter-ticker",
                                                className="dd-blend",
                                                options=[{"label": "All", "value": "all"}],
                                                value="all",
                                                clearable=False,
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Strategy", className="field-label"),
                                            dcc.Dropdown(
                                                id="backlog-filter-strategy",
                                                className="dd-blend",
                                                options=[{"label": "All", "value": "all"}],
                                                value="all",
                                                clearable=False,
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Signal", className="field-label"),
                                            dcc.Dropdown(
                                                id="backlog-filter-signal",
                                                className="dd-blend",
                                                options=[
                                                    {"label": "All", "value": "all"},
                                                    {"label": "BUY", "value": "BUY"},
                                                    {"label": "SELL", "value": "SELL"},
                                                    {"label": "HOLD", "value": "HOLD"},
                                                    {"label": "DATA", "value": "DATA"},
                                                ],
                                                value="all",
                                                clearable=False,
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                        ],
                    ),

                    # Backlog table
                    html.Div(
                        className="card",
                        children=[
                            html.Div(
                                className="card-title-row",
                                children=[
                                    html.Div("Signals History", className="card-title"),
                                    html.Div("Last 100 signals", className="hint-text"),
                                ],
                            ),
                            DataTable(
                                id="signals-backlog-table",
                                columns=[
                                    {"name": "Timestamp", "id": "timestamp"},
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Strategy", "id": "strategy"},
                                    {"name": "Signal", "id": "signal"},
                                    {"name": "Reason", "id": "reason"},
                                ],
                                data=[],
                                page_size=20,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def bucket_rows(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Bucket signal rows into Priority, Hold, and Risk categories.

    Args:
        rows: List of signal row dicts with cas, cas_verdict, and signal keys

    Returns:
        Tuple of (priority_rows, hold_rows, risk_rows)
    """
    priority_rows = []
    hold_rows = []
    risk_rows = []

    for row in rows:
        cas = row.get("cas", 50)
        verdict = row.get("cas_verdict", "HOLD")
        signal = row.get("signal", "HOLD")

        # Priority: CAS >= 75 AND signal != SELL
        if cas >= 75 and signal != "SELL":
            priority_rows.append(row)
        # Risk: CAS < 45 OR signal == SELL
        elif cas < 45 or signal == "SELL":
            risk_rows.append(row)
        # Hold: Everything else (CAS 45-74, or other conditions)
        else:
            hold_rows.append(row)

    return priority_rows, hold_rows, risk_rows


@callback(
    Output("signals-portfolio", "options"),
    Output("signals-portfolio", "value"),
    Input("url", "pathname"),
)
def populate_portfolio_dropdown(pathname):
    """Populate portfolio dropdown on page load."""
    if pathname != "/portfolio/signals":
        raise PreventUpdate
    portfolios = list_portfolios()
    if not portfolios:
        return [], None
    options = [{"label": p["name"], "value": p["id"]} for p in portfolios]
    return options, portfolios[0]["id"]


@callback(
    Output("signals-status", "children", allow_duplicate=True),
    Input("signals-portfolio", "value"),
    prevent_initial_call=True,
)
def show_portfolio_warning(portfolio_id):
    """Show warning if portfolio_id != 1 (Technical Backtest uses portfolio_id=1)."""
    if portfolio_id is None:
        raise PreventUpdate

    if portfolio_id != 1:
        return html.Div(
            [
                html.Strong("⚠️ Portfolio Mismatch: "),
                "Assignments are stored per portfolio. ",
                "Technical Backtest currently uses Portfolio ID 1. ",
                "If you assigned strategies there, select that portfolio here to see them.",
            ],
            style={
                "color": "#856404",
                "backgroundColor": "#fff3cd",
                "padding": "10px 14px",
                "borderRadius": "4px",
                "fontSize": "14px",
                "marginBottom": "14px",
            },
        )

    return None


@callback(
    Output("signals-panel-overview", "style"),
    Output("signals-panel-manage", "style"),
    Output("signals-panel-backlog", "style"),
    Output("signals-nav-overview", "active"),
    Output("signals-nav-manage", "active"),
    Output("signals-nav-backlog", "active"),
    Output("signals-nav-overview", "style"),
    Output("signals-nav-manage", "style"),
    Output("signals-nav-backlog", "style"),
    Input("signals-nav-overview", "n_clicks"),
    Input("signals-nav-manage", "n_clicks"),
    Input("signals-nav-backlog", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_signals_panels(overview_clicks, manage_clicks, backlog_clicks):
    """Toggle between 3 panels based on pill clicks."""
    from dash import ctx

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Default: all hidden, all inactive
    panel_styles = {
        "overview": {"display": "none"},
        "manage": {"display": "none"},
        "backlog": {"display": "none"},
    }
    active_states = {
        "overview": False,
        "manage": False,
        "backlog": False,
    }
    pill_styles = {
        "overview": PILL_INACTIVE_STYLE,
        "manage": PILL_INACTIVE_STYLE,
        "backlog": PILL_INACTIVE_STYLE,
    }

    # Determine which tab was clicked
    if button_id == "signals-nav-overview":
        panel_styles["overview"] = {"display": "block"}
        active_states["overview"] = True
        pill_styles["overview"] = PILL_ACTIVE_STYLE
    elif button_id == "signals-nav-manage":
        panel_styles["manage"] = {"display": "block"}
        active_states["manage"] = True
        pill_styles["manage"] = PILL_ACTIVE_STYLE
    elif button_id == "signals-nav-backlog":
        panel_styles["backlog"] = {"display": "block"}
        active_states["backlog"] = True
        pill_styles["backlog"] = PILL_ACTIVE_STYLE
    else:
        raise PreventUpdate

    return (
        panel_styles["overview"],
        panel_styles["manage"],
        panel_styles["backlog"],
        active_states["overview"],
        active_states["manage"],
        active_states["backlog"],
        pill_styles["overview"],
        pill_styles["manage"],
        pill_styles["backlog"],
    )


@callback(
    Output("signals-priority-table", "data"),
    Output("signals-hold-table", "data"),
    Output("signals-risk-table", "data"),
    Output("signals-brief", "children"),
    Output("strategy-assign-ticker", "options"),
    Output("strategy-assign-strategy", "options"),
    Input("signals-portfolio", "value"),
    Input("watchlist-version", "data"),
)
def refresh_signals_overview(portfolio_id, _watchlist_ver):
    """Refresh signal overview tables and brief when portfolio or watchlist changes."""
    if portfolio_id is None:
        raise PreventUpdate

    # Positions & trades
    trades = list_trades(portfolio_id, limit=1000)
    positions = compute_positions(trades)
    position_tickers = [p["ticker"] for p in positions]

    # Watchlist tickers
    watchlist_entries = list_watchlist(portfolio_id)
    watchlist_tickers = [w["ticker"] for w in watchlist_entries]

    # All tickers deduplicated (positions first)
    all_tickers = list(dict.fromkeys(position_tickers + watchlist_tickers))

    # Fetch native-currency prices for all
    prices, _ = get_latest_daily_closes_cached(
        all_tickers,
        max_age_minutes=60,
        force_refresh=False,
    )

    # Strategy assignments  {ticker: saved_strategy_id}
    assignment_map = get_assignment_map(portfolio_id)

    # --- position rows ---------------------------------------------------
    signal_rows = []
    for pos in positions:
        ticker = pos["ticker"]
        shares = pos["shares"]
        last_price = prices.get(ticker)
        saved_strategy_id = assignment_map.get(ticker)

        if last_price is None:
            signal, reason, strategy_display = "DATA", "Missing price data", "None"
        elif saved_strategy_id is None:
            signal, reason, strategy_display = "HOLD", "No strategy assigned", "None"
        else:
            saved_strategy = get_saved_strategy_by_id(portfolio_id, saved_strategy_id)
            if saved_strategy:
                strategy_display = f"{saved_strategy['name']} ({saved_strategy['base_strategy_key']})"
                result = evaluate_position_signal(ticker, saved_strategy, last_price, trades)
                signal = result["signal"]
                reason = result["reason"]
            else:
                signal, reason = "DATA", "Assigned strategy not found"
                strategy_display = "ERROR: Strategy not found"

        signal_rows.append({
            "ticker": ticker,
            "mode": "Position",
            "shares": round(shares, 4),
            "last_price": f"{last_price:.2f}" if last_price else "N/A",
            "signal": signal,
            "strategy": strategy_display,
            "conflicts": "",
            "reason": reason,
        })

    # --- watchlist rows (skip tickers already covered by positions) -------
    position_set = set(position_tickers)
    for ticker in watchlist_tickers:
        if ticker in position_set:
            continue  # position row already emitted

        last_price = prices.get(ticker)
        saved_strategy_id = assignment_map.get(ticker)

        if last_price is None:
            signal, reason, strategy_display = "DATA", "Missing price data", "None"
        elif saved_strategy_id is None:
            signal, reason, strategy_display = "HOLD", "No strategy assigned", "None"
        else:
            saved_strategy = get_saved_strategy_by_id(portfolio_id, saved_strategy_id)
            if saved_strategy:
                strategy_display = f"{saved_strategy['name']} ({saved_strategy['base_strategy_key']})"
                result = evaluate_watchlist_signal(ticker, saved_strategy)
                signal = result["signal"]
                reason = result["reason"]
            else:
                signal, reason = "DATA", "Assigned strategy not found"
                strategy_display = "ERROR: Strategy not found"

        signal_rows.append({
            "ticker": ticker,
            "mode": "Watchlist",
            "shares": 0,
            "last_price": f"{last_price:.2f}" if last_price else "N/A",
            "signal": signal,
            "strategy": strategy_display,
            "conflicts": "",
            "reason": reason,
        })

    # --- Compute CAS for all rows -----------------------------------------------
    # Load policy and cash balance for CAS context
    policy = load_policy_snapshot(portfolio_id).get("policy", {})
    cash_movements = list_cash_movements(portfolio_id, limit=1000)
    cash_balance = compute_cash_balance(cash_movements, trades)

    # Build fundamentals map {ticker: fundamental_score}
    fundamentals_map = {}
    for ticker in all_tickers:
        fund_data = get_latest_fundamentals_for_ticker(ticker)
        if fund_data and fund_data.get("bench_score_total") is not None:
            try:
                bench_score = float(fund_data["bench_score_total"])
                confidence = float(fund_data.get("bench_confidence", 100))
                fundamental_score = (bench_score * confidence) / 100
                fundamentals_map[ticker] = fundamental_score
            except (ValueError, TypeError):
                # Skip if conversion fails
                pass

    # Compute CAS for all rows
    signal_rows = compute_cas_for_rows(
        signal_rows,
        positions,
        prices,
        cash_balance,
        policy=policy,
        fundamentals_map=fundamentals_map,
    )

    # Bucket rows into Priority, Hold, and Risk
    priority_rows, hold_rows, risk_rows = bucket_rows(signal_rows)

    # Build allocation brief
    priority_count = len(priority_rows)
    hold_count = len(hold_rows)
    risk_count = len(risk_rows)
    sell_count = sum(1 for r in signal_rows if r.get("signal") == "SELL")

    # Build brief content
    brief_content = [
        html.Div(
            className="grid-3",
            style={"marginBottom": "12px"},
            children=[
                html.Div([
                    html.Div(f"{priority_count}", style={"fontSize": "24px", "fontWeight": "600", "color": "#2ecc71"}),
                    html.Div("Priority", style={"fontSize": "12px", "color": "var(--text-muted)"}),
                ]),
                html.Div([
                    html.Div(f"{hold_count}", style={"fontSize": "24px", "fontWeight": "600", "color": "#f39c12"}),
                    html.Div("Hold", style={"fontSize": "12px", "color": "var(--text-muted)"}),
                ]),
                html.Div([
                    html.Div(f"{risk_count}", style={"fontSize": "24px", "fontWeight": "600", "color": "#e74c3c"}),
                    html.Div("Risk", style={"fontSize": "12px", "color": "var(--text-muted)"}),
                ]),
            ],
        ),
    ]

    # Next best action
    if priority_count > 0:
        top_priority = max(priority_rows, key=lambda r: r.get("cas", 0))
        top_ticker = top_priority.get("ticker", "—")
        top_cas = top_priority.get("cas", 0)
        action_text = f"If you add money this month, start with {top_ticker} (CAS {top_cas:.0f})."
    else:
        action_text = "No priority buys today. Focus on contributions and staying within policy."

    brief_content.append(
        html.Div(action_text, style={"marginBottom": "8px", "fontSize": "14px"})
    )

    # SELL warning
    if sell_count > 0:
        brief_content.append(
            html.Div(
                f"There are {sell_count} SELL signals; consider trims only if aligned with your long-term plan.",
                style={"fontSize": "13px", "color": "var(--danger)", "marginBottom": "8px"},
            )
        )

    # CAS formula legend
    brief_content.append(
        html.Div(
            "CAS = 35% Fundamental + 25% Trend + 20% Fit + 15% Risk + 5% Cash",
            style={"fontSize": "11px", "color": "var(--text-muted)", "marginTop": "10px"},
        )
    )

    # Ticker options: positions + watchlist
    ticker_options = [{"label": t, "value": t} for t in sorted(set(all_tickers))]

    return priority_rows, hold_rows, risk_rows, brief_content, ticker_options, []


@callback(
    Output("strategy-assign-strategy", "options", allow_duplicate=True),
    Input("signals-portfolio", "value"),
    Input("strategy-assign-ticker", "value"),
    prevent_initial_call=True,
)
def populate_strategy_dropdown(portfolio_id, ticker):
    """Populate strategy dropdown with saved strategies for the selected ticker."""
    if portfolio_id is None or not ticker:
        return []

    # List saved strategies for this ticker
    saved_strategies = list_saved_strategies(portfolio_id, ticker)

    if not saved_strategies:
        return []

    # Build options: label shows name and base strategy, value is saved_strategy_id
    options = [
        {
            "label": f"{s['name']} ({s['base_strategy_key']})",
            "value": s["id"]
        }
        for s in saved_strategies
    ]

    return options


@callback(
    Output("signals-manage-table", "data"),
    Input("signals-portfolio", "value"),
    Input("watchlist-version", "data"),
)
def refresh_strategy_assignments(portfolio_id, _watchlist_ver):
    """Refresh strategy assignments table (positions + watchlist)."""
    if portfolio_id is None:
        raise PreventUpdate

    # Positions
    trades = list_trades(portfolio_id, limit=1000)
    positions = compute_positions(trades)
    position_tickers = {p["ticker"] for p in positions}

    # Watchlist
    watchlist_tickers = {w["ticker"] for w in list_watchlist(portfolio_id)}

    # All tickers deduplicated
    all_tickers = sorted(position_tickers | watchlist_tickers)

    # Strategy assignments
    assignment_map = get_assignment_map(portfolio_id)

    assignment_rows = []
    for ticker in all_tickers:
        saved_strategy_id = assignment_map.get(ticker)
        mode = "Position" if ticker in position_tickers else "Watchlist"

        if saved_strategy_id:
            saved_strategy = get_saved_strategy_by_id(portfolio_id, saved_strategy_id)
            if saved_strategy:
                strategy_display = f"{saved_strategy['name']} ({saved_strategy['base_strategy_key']})"
                status = f"Assigned ({mode})"
            else:
                strategy_display = "ERROR: Not found"
                status = "Error"
        else:
            strategy_display = "None"
            status = f"Unassigned ({mode})"

        assignment_rows.append({
            "ticker": ticker,
            "strategy": strategy_display,
            "status": status,
        })

    return assignment_rows


@callback(
    Output("strategy-preview-content", "children"),
    Input("strategy-assign-strategy", "value"),
    Input("signals-portfolio", "value"),
    Input("strategy-assign-ticker", "value"),
)
def update_strategy_preview(saved_strategy_id, portfolio_id, ticker):
    """Update strategy preview when strategy selection changes."""
    if not saved_strategy_id or portfolio_id is None or not ticker:
        return "Select a strategy to view details"

    # Get saved strategy details
    saved_strategy = get_saved_strategy_by_id(portfolio_id, saved_strategy_id)

    if not saved_strategy:
        return "Strategy not found"

    # Format parameters (show first 6 keys)
    params = saved_strategy.get("params", {})
    param_keys = list(params.keys())[:6]
    param_summary = ", ".join([f"{k}={params[k]}" for k in param_keys])
    if len(params) > 6:
        param_summary += f" ... ({len(params) - 6} more)"

    return html.Div(
        children=[
            html.Div(
                saved_strategy["name"],
                style={"fontSize": "16px", "fontWeight": "600", "marginBottom": "8px"},
            ),
            html.Div(
                f"Base Strategy: {saved_strategy['base_strategy_key']}",
                style={"marginBottom": "8px", "color": "var(--text-secondary)"},
            ),
            html.Div(
                f"Ticker: {saved_strategy['ticker']}",
                style={"marginBottom": "8px", "fontSize": "13px", "color": "var(--text-hint)"},
            ),
            html.Div(
                f"Parameters: {param_summary}",
                style={"fontSize": "13px", "color": "var(--text-hint)"},
            ),
            html.Div(
                saved_strategy.get("notes", ""),
                style={"marginTop": "8px", "fontSize": "12px", "fontStyle": "italic", "color": "var(--text-hint)"},
            ) if saved_strategy.get("notes") else None,
        ]
    )


@callback(
    Output("signals-status", "children"),
    Output("signals-manage-table", "data", allow_duplicate=True),
    Output("watchlist-version", "data", allow_duplicate=True),
    Input("strategy-assign-btn", "n_clicks"),
    Input("signals-portfolio", "value"),
    Input("strategy-assign-ticker", "value"),
    Input("strategy-assign-strategy", "value"),
    State("watchlist-version", "data"),
    prevent_initial_call=True,
)
def handle_strategy_assignment(n_clicks, portfolio_id, ticker, saved_strategy_id, current_version):
    """Handle strategy assignment to ticker (also bumps overview refresh)."""
    if not n_clicks or portfolio_id is None or not ticker or not saved_strategy_id:
        raise PreventUpdate

    # Assign saved strategy
    try:
        assign_saved_strategy(portfolio_id, ticker, saved_strategy_id)
    except Exception as e:
        error_status = html.Div(
            f"Assignment failed: {str(e)}",
            style={
                "color": "#721c24",
                "backgroundColor": "#f8d7da",
                "padding": "10px 14px",
                "borderRadius": "4px",
                "fontSize": "14px",
            },
        )
        return error_status, no_update, no_update

    # Success status
    success_status = html.Div(
        f"Strategy assigned to {ticker.upper()} successfully",
        style={
            "color": "#155724",
            "backgroundColor": "#d4edda",
            "padding": "10px 14px",
            "borderRadius": "4px",
            "fontSize": "14px",
        },
    )

    # Refresh assignments table (include watchlist tickers)
    trades = list_trades(portfolio_id, limit=1000)
    positions = compute_positions(trades)
    position_tickers = {p["ticker"] for p in positions}
    watchlist_tickers = {w["ticker"] for w in list_watchlist(portfolio_id)}
    all_tickers = sorted(position_tickers | watchlist_tickers)

    assignment_map = get_assignment_map(portfolio_id)

    assignment_rows = []
    for t in all_tickers:
        sid = assignment_map.get(t)
        mode = "Position" if t in position_tickers else "Watchlist"
        if sid:
            saved = get_saved_strategy_by_id(portfolio_id, sid)
            strategy_display = f"{saved['name']} ({saved['base_strategy_key']})" if saved else "ERROR: Not found"
            status = f"Assigned ({mode})" if saved else "Error"
        else:
            strategy_display = "None"
            status = f"Unassigned ({mode})"

        assignment_rows.append({
            "ticker": t,
            "strategy": strategy_display,
            "status": status,
        })

    return success_status, assignment_rows, (current_version or 0) + 1


@callback(
    Output("signals-backlog-table", "data"),
    Input("signals-portfolio", "value"),
    Input("backlog-filter-ticker", "value"),
    Input("backlog-filter-strategy", "value"),
    Input("backlog-filter-signal", "value"),
)
def refresh_signals_backlog(portfolio_id, filter_ticker, filter_strategy, filter_signal):
    """Refresh signals backlog with optional filters."""
    if portfolio_id is None:
        raise PreventUpdate

    # Fetch backlog
    backlog = list_signals_backlog(portfolio_id, limit=100)

    # Apply filters (simple client-side filtering)
    filtered_backlog = []
    for entry in backlog:
        if filter_ticker != "all" and entry.get("ticker") != filter_ticker:
            continue
        if filter_strategy != "all" and entry.get("strategy_key") != filter_strategy:
            continue
        if filter_signal != "all" and entry.get("signal") != filter_signal:
            continue

        filtered_backlog.append({
            "timestamp": entry.get("ts", ""),
            "ticker": entry.get("ticker", ""),
            "strategy": entry.get("strategy_key", ""),
            "signal": entry.get("signal", ""),
            "reason": entry.get("reason", ""),
        })

    return filtered_backlog


@callback(
    Output("watchlist-table", "data"),
    Output("watchlist-remove-ticker", "options"),
    Input("signals-portfolio", "value"),
    Input("watchlist-version", "data"),
)
def refresh_watchlist_table(portfolio_id, _watchlist_ver):
    """Populate watchlist table and remove dropdown."""
    if portfolio_id is None:
        raise PreventUpdate

    watchlist = list_watchlist(portfolio_id)
    assignment_map = get_assignment_map(portfolio_id)

    rows = []
    for w in watchlist:
        ticker = w["ticker"]
        sid = assignment_map.get(ticker)
        strategy_name = "None"
        if sid:
            saved = get_saved_strategy_by_id(portfolio_id, sid)
            if saved:
                strategy_name = f"{saved['name']} ({saved['base_strategy_key']})"
        rows.append({
            "ticker": ticker,
            "strategy": strategy_name,
            "notes": w.get("notes", ""),
            "added_at": w.get("added_at", ""),
        })

    remove_options = [{"label": w["ticker"], "value": w["ticker"]} for w in watchlist]
    return rows, remove_options


@callback(
    Output("watchlist-status", "children"),
    Output("watchlist-version", "data"),
    Output("watchlist-table", "data", allow_duplicate=True),
    Output("watchlist-remove-ticker", "options", allow_duplicate=True),
    Output("watchlist-ticker-input", "value"),
    Input("watchlist-add-btn", "n_clicks"),
    State("signals-portfolio", "value"),
    State("watchlist-ticker-input", "value"),
    State("watchlist-version", "data"),
    prevent_initial_call=True,
)
def handle_add_to_watchlist(n_clicks, portfolio_id, ticker_input, current_version):
    """Add a ticker to the watchlist."""
    if not n_clicks or portfolio_id is None or not ticker_input:
        raise PreventUpdate

    ticker = ticker_input.strip().upper()
    if not ticker:
        raise PreventUpdate

    try:
        add_to_watchlist(portfolio_id, ticker)
    except Exception as e:
        return (
            html.Div(f"Failed to add {ticker}: {e}", style={"color": "#721c24", "backgroundColor": "#f8d7da", "padding": "8px 12px", "borderRadius": "4px", "fontSize": "13px"}),
            no_update, no_update, no_update, "",
        )

    # Refresh watchlist data
    watchlist = list_watchlist(portfolio_id)
    assignment_map = get_assignment_map(portfolio_id)
    rows = []
    for w in watchlist:
        t = w["ticker"]
        sid = assignment_map.get(t)
        sname = "None"
        if sid:
            saved = get_saved_strategy_by_id(portfolio_id, sid)
            if saved:
                sname = f"{saved['name']} ({saved['base_strategy_key']})"
        rows.append({"ticker": t, "strategy": sname, "notes": w.get("notes", ""), "added_at": w.get("added_at", "")})

    remove_opts = [{"label": w["ticker"], "value": w["ticker"]} for w in watchlist]
    success = html.Div(f"{ticker} added to watchlist", style={"color": "#155724", "backgroundColor": "#d4edda", "padding": "8px 12px", "borderRadius": "4px", "fontSize": "13px"})
    return success, (current_version or 0) + 1, rows, remove_opts, ""


@callback(
    Output("watchlist-status", "children", allow_duplicate=True),
    Output("watchlist-version", "data", allow_duplicate=True),
    Output("watchlist-table", "data", allow_duplicate=True),
    Output("watchlist-remove-ticker", "options", allow_duplicate=True),
    Input("watchlist-remove-btn", "n_clicks"),
    State("signals-portfolio", "value"),
    State("watchlist-remove-ticker", "value"),
    State("watchlist-version", "data"),
    prevent_initial_call=True,
)
def handle_remove_from_watchlist(n_clicks, portfolio_id, ticker, current_version):
    """Remove a ticker from the watchlist."""
    if not n_clicks or portfolio_id is None or not ticker:
        raise PreventUpdate

    try:
        remove_from_watchlist(portfolio_id, ticker)
    except Exception as e:
        return (
            html.Div(f"Failed to remove {ticker}: {e}", style={"color": "#721c24", "backgroundColor": "#f8d7da", "padding": "8px 12px", "borderRadius": "4px", "fontSize": "13px"}),
            no_update, no_update, no_update,
        )

    # Refresh watchlist data
    watchlist = list_watchlist(portfolio_id)
    assignment_map = get_assignment_map(portfolio_id)
    rows = []
    for w in watchlist:
        t = w["ticker"]
        sid = assignment_map.get(t)
        sname = "None"
        if sid:
            saved = get_saved_strategy_by_id(portfolio_id, sid)
            if saved:
                sname = f"{saved['name']} ({saved['base_strategy_key']})"
        rows.append({"ticker": t, "strategy": sname, "notes": w.get("notes", ""), "added_at": w.get("added_at", "")})

    remove_opts = [{"label": w["ticker"], "value": w["ticker"]} for w in watchlist]
    success = html.Div(f"{ticker} removed from watchlist", style={"color": "#155724", "backgroundColor": "#d4edda", "padding": "8px 12px", "borderRadius": "4px", "fontSize": "13px"})
    return success, (current_version or 0) + 1, rows, remove_opts


@callback(
    Output("signals-hold-visible", "data"),
    Output("signals-hold-section", "style"),
    Input("signals-hold-toggle-btn", "n_clicks"),
    State("signals-hold-visible", "data"),
    prevent_initial_call=True,
)
def toggle_hold_section(n_clicks, current_visible):
    """Toggle visibility of Hold & Monitor section."""
    new_visible = not current_visible
    style = {"display": "block"} if new_visible else {"display": "none"}
    return new_visible, style


@callback(
    Output("signals-risk-visible", "data"),
    Output("signals-risk-section", "style"),
    Input("signals-risk-toggle-btn", "n_clicks"),
    State("signals-risk-visible", "data"),
    prevent_initial_call=True,
)
def toggle_risk_section(n_clicks, current_visible):
    """Toggle visibility of Capital at Risk section."""
    new_visible = not current_visible
    style = {"display": "block"} if new_visible else {"display": "none"}
    return new_visible, style
