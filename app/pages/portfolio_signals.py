from __future__ import annotations
import dash_bootstrap_components as dbc

from dash import dcc, html, Input, Output, callback, no_update
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate

from app.db.portfolio_repo import list_portfolios
from app.db.ledger_repo import list_trades
from app.db.signals_repo import (
    list_strategy_definitions,
    get_ticker_strategy_map,
    upsert_ticker_strategy,
    list_signals_backlog,
)
from app.domain.ledger import compute_positions
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
                    html.Div(
                        className="card",
                        children=[
                            html.Div(
                                className="card-title-row",
                                children=[
                                    html.Div("Current Signals", className="card-title"),
                                    html.Div("Live signals based on latest prices and strategy assignments", className="hint-text"),
                                ],
                            ),
                            DataTable(
                                id="signals-overview-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Shares", "id": "shares", "type": "numeric"},
                                    {"name": "Last Price", "id": "last_price", "type": "numeric"},
                                    {"name": "Signal", "id": "signal"},
                                    {"name": "Strategy", "id": "strategy"},
                                    {"name": "Conflicts", "id": "conflicts"},
                                    {"name": "Reason", "id": "reason"},
                                ],
                                data=[],
                                page_size=20,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                                style_data_conditional=[
                                    {
                                        "if": {"filter_query": "{signal} = BUY"},
                                        "backgroundColor": "rgba(40, 167, 69, 0.15)",
                                    },
                                    {
                                        "if": {"filter_query": "{signal} = SELL"},
                                        "backgroundColor": "rgba(220, 53, 69, 0.15)",
                                    },
                                    {
                                        "if": {"filter_query": "{signal} = DATA"},
                                        "backgroundColor": "rgba(255, 193, 7, 0.15)",
                                    },
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
        style={"maxWidth": "1100px"},
    )


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
    Output("signals-overview-table", "data"),
    Output("strategy-assign-ticker", "options"),
    Output("strategy-assign-strategy", "options"),
    Input("signals-portfolio", "value"),
)
def refresh_signals_overview(portfolio_id):
    """Refresh signal overview table when portfolio changes."""
    if portfolio_id is None:
        raise PreventUpdate

    # Fetch positions and prices
    trades = list_trades(portfolio_id, limit=1000)
    positions = compute_positions(trades)
    ticker_list = [p["ticker"] for p in positions]

    # Fetch prices
    prices, missing_tickers = get_latest_daily_closes_cached(
        ticker_list,
        max_age_minutes=60,
        force_refresh=False,
    )

    # Fetch strategy assignments
    strategy_map = get_ticker_strategy_map(portfolio_id)
    strategies = list_strategy_definitions()

    # Build signal rows
    signal_rows = []
    for pos in positions:
        ticker = pos["ticker"]
        shares = pos["shares"]
        last_price = prices.get(ticker, None)
        strategy_key = strategy_map.get(ticker, None)

        # Signal logic
        if last_price is None:
            signal = "DATA"
            reason = "Missing price data"
        elif strategy_key is None:
            signal = "HOLD"
            reason = "No strategy assigned"
        else:
            signal = "HOLD"
            reason = "Strategy applied (placeholder logic)"

        # Strategy name lookup
        strategy_name = next((s["name"] for s in strategies if s["strategy_key"] == strategy_key), "None") if strategy_key else "None"

        signal_rows.append({
            "ticker": ticker,
            "shares": round(shares, 4),
            "last_price": f"€{last_price:.2f}" if last_price else "N/A",
            "signal": signal,
            "strategy": strategy_name,
            "conflicts": "",
            "reason": reason,
        })

    # Populate ticker dropdown for assignment
    ticker_options = [{"label": t, "value": t} for t in sorted(ticker_list)]

    # Populate strategy dropdown
    strategy_options = [{"label": s["name"], "value": s["strategy_key"]} for s in strategies]

    return signal_rows, ticker_options, strategy_options


@callback(
    Output("signals-manage-table", "data"),
    Input("signals-portfolio", "value"),
)
def refresh_strategy_assignments(portfolio_id):
    """Refresh strategy assignments table."""
    if portfolio_id is None:
        raise PreventUpdate

    # Fetch trades and positions
    trades = list_trades(portfolio_id, limit=1000)
    positions = compute_positions(trades)
    ticker_list = [p["ticker"] for p in positions]

    # Fetch strategy assignments
    strategy_map = get_ticker_strategy_map(portfolio_id)
    strategies = list_strategy_definitions()

    # Build assignment rows
    assignment_rows = []
    for ticker in sorted(ticker_list):
        strategy_key = strategy_map.get(ticker, None)
        strategy_name = next((s["name"] for s in strategies if s["strategy_key"] == strategy_key), "None") if strategy_key else "None"
        status = "Assigned" if strategy_key else "Unassigned"

        assignment_rows.append({
            "ticker": ticker,
            "strategy": strategy_name,
            "status": status,
        })

    return assignment_rows


@callback(
    Output("strategy-preview-content", "children"),
    Input("strategy-assign-strategy", "value"),
)
def update_strategy_preview(strategy_key):
    """Update strategy preview when strategy selection changes."""
    if not strategy_key:
        return "Select a strategy to view details"

    strategies = list_strategy_definitions()
    strategy = next((s for s in strategies if s["strategy_key"] == strategy_key), None)

    if not strategy:
        return "Strategy not found"

    return html.Div(
        children=[
            html.Div(
                strategy["name"],
                style={"fontSize": "16px", "fontWeight": "600", "marginBottom": "8px"},
            ),
            html.Div(
                strategy.get("description", "No description available"),
                style={"marginBottom": "8px", "color": "var(--text-secondary)"},
            ),
            html.Div(
                f"Parameters: {strategy.get('params_json', '{}')}",
                style={"fontSize": "13px", "color": "var(--text-hint)"},
            ),
        ]
    )


@callback(
    Output("signals-status", "children"),
    Output("signals-manage-table", "data", allow_duplicate=True),
    Input("strategy-assign-btn", "n_clicks"),
    Input("signals-portfolio", "value"),
    Input("strategy-assign-ticker", "value"),
    Input("strategy-assign-strategy", "value"),
    prevent_initial_call=True,
)
def handle_strategy_assignment(n_clicks, portfolio_id, ticker, strategy_key):
    """Handle strategy assignment to ticker."""
    if not n_clicks or portfolio_id is None or not ticker or not strategy_key:
        raise PreventUpdate

    # Assign strategy
    try:
        upsert_ticker_strategy(portfolio_id, ticker, strategy_key)
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
        return error_status, no_update

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

    # Refresh assignments table
    trades = list_trades(portfolio_id, limit=1000)
    positions = compute_positions(trades)
    ticker_list = [p["ticker"] for p in positions]

    strategy_map = get_ticker_strategy_map(portfolio_id)
    strategies = list_strategy_definitions()

    assignment_rows = []
    for t in sorted(ticker_list):
        sk = strategy_map.get(t, None)
        sn = next((s["name"] for s in strategies if s["strategy_key"] == sk), "None") if sk else "None"
        status = "Assigned" if sk else "Unassigned"

        assignment_rows.append({
            "ticker": t,
            "strategy": sn,
            "status": status,
        })

    return success_status, assignment_rows


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
