from __future__ import annotations

import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from dash import dcc, html, Input, Output, State, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate
from datetime import datetime, timedelta

from app.db.benchmarks_repo import (
    list_benchmarks,
    add_benchmark,
    delete_benchmark,
    get_benchmark_eod,
    ensure_benchmark_eod_cached,
    get_latest_snapshot_all_benchmarks,
    upsert_benchmark_tickers,
    get_benchmark_tickers_with_fundamentals,
    refresh_benchmark_fundamentals,
)

# Pill styling constants (match portfolio_design.py)
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


def calculate_ema(prices: list[float], period: int) -> list[float]:
    """Calculate Exponential Moving Average."""
    if len(prices) < period:
        return [None] * len(prices)
    ema = []
    alpha = 2 / (period + 1)
    sma = sum(prices[:period]) / period
    ema.extend([None] * (period - 1))
    ema.append(sma)
    for price in prices[period:]:
        ema.append(price * alpha + ema[-1] * (1 - alpha))
    return ema


def create_benchmark_chart(benchmark_id: int, ticker: str, name: str) -> go.Figure:
    """Create a line chart with close price, EMA20, and EMA50."""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        # Ensure data is cached
        ensure_benchmark_eod_cached(benchmark_id, ticker, start_date, end_date)

        # Fetch cached data
        bars = get_benchmark_eod(benchmark_id, start_date, end_date)

        if not bars:
            fig = go.Figure()
            fig.add_annotation(
                text="No data available",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color="#6b7280"),
            )
            fig.update_layout(
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                margin=dict(l=0, r=0, t=0, b=0),
                height=200,
            )
            return fig

        dates = [bar["date"] for bar in bars]
        closes = [bar["close"] for bar in bars]

        # Calculate EMAs
        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)

        # Create traces
        fig = go.Figure()

        # Close price (solid blue line)
        fig.add_trace(go.Scatter(
            x=dates,
            y=closes,
            mode="lines",
            name="Close",
            line=dict(color="#2D7DFF", width=2),
        ))

        # EMA20 (dashed cyan line)
        fig.add_trace(go.Scatter(
            x=dates,
            y=ema20,
            mode="lines",
            name="EMA20",
            line=dict(color="#32C5FF", width=1.5, dash="dash"),
        ))

        # EMA50 (dashed orange line)
        fig.add_trace(go.Scatter(
            x=dates,
            y=ema50,
            mode="lines",
            name="EMA50",
            line=dict(color="#fb923c", width=1.5, dash="dash"),
        ))

        fig.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(size=10),
            ),
            margin=dict(l=40, r=10, t=30, b=30),
            height=200,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter", size=11, color="rgba(255,255,255,0.85)"),
            xaxis=dict(
                gridcolor="rgba(255,255,255,0.08)",
                showgrid=True,
                title=None,
            ),
            yaxis=dict(
                gridcolor="rgba(255,255,255,0.08)",
                showgrid=True,
                title=None,
            ),
        )

        return fig

    except Exception as e:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Error: {str(e)}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=12, color="#FF4D6D"),
        )
        fig.update_layout(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            margin=dict(l=0, r=0, t=0, b=0),
            height=200,
        )
        return fig


def layout() -> html.Div:
    return html.Div(
        children=[
            # Store for triggering data refresh after CRUD operations
            dcc.Store(id="market-refresh-trigger", data=0),

            # Page header
            html.Div(
                className="page-header",
                children=[
                    html.Div(
                        children=[
                            html.H2("Analytics – Market", style={"margin": "0"}),
                            html.Div(
                                "Track benchmark indices and market trends.",
                                className="page-subtitle",
                            ),
                        ]
                    ),
                    html.Div(
                        className="page-header-actions",
                        children=[
                            html.Button(
                                "Refresh",
                                id="market-breakdown-refresh-btn",
                                className="btn-primary",
                                n_clicks=0,
                            ),
                            html.Div(
                                children=[
                                    html.Div("Benchmark", className="field-label"),
                                    dcc.Dropdown(
                                        id="market-breakdown-benchmark",
                                        options=[],
                                        value=None,
                                        placeholder="Select benchmark",
                                        clearable=True,
                                        style={"minWidth": "220px"},
                                    ),
                                ]
                            ),
                        ],
                    ),
                ],
            ),

            # Status bar
            html.Div(
                id="market-status-bar",
                className="status-bar",
                children="Loading benchmarks...",
            ),

            # Nav pills for panel navigation
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    dbc.Nav(
                        pills=True,
                        className="segmented-pills",
                        children=[
                            dbc.NavLink(
                                "Overview",
                                id="market-nav-overview",
                                active=True,
                                style=PILL_ACTIVE_STYLE,
                            ),
                            dbc.NavLink(
                                "Breakdown",
                                id="market-nav-breakdown",
                                active=False,
                                style=PILL_INACTIVE_STYLE,
                            ),
                            dbc.NavLink(
                                "Settings",
                                id="market-nav-settings",
                                active=False,
                                style=PILL_INACTIVE_STYLE,
                            ),
                        ],
                    ),
                ],
            ),

            # Panel 1: Overview (visible by default)
            html.Div(
                id="market-panel-overview",
                style={"display": "block"},
                children=[
                    # Benchmark cards grid
                    html.Div(
                        id="market-cards-container",
                        className="grid-3",
                        style={"marginBottom": "14px"},
                        children=[],
                    ),
                    # Snapshot table
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Benchmark Snapshot", className="card-title"),
                            DataTable(
                                id="market-snapshot-table",
                                columns=[
                                    {"name": "Benchmark", "id": "name"},
                                    {"name": "Region", "id": "region"},
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Latest Date", "id": "latest_date"},
                                    {"name": "Close", "id": "latest_close", "type": "numeric", "format": {"specifier": ".2f"}},
                                    {"name": "Change %", "id": "change_pct", "type": "numeric", "format": {"specifier": ".2f"}},
                                ],
                                data=[],
                                page_size=10,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                                style_data_conditional=[
                                    {
                                        "if": {"filter_query": "{change_pct} > 0", "column_id": "change_pct"},
                                        "color": "var(--ok)",
                                    },
                                    {
                                        "if": {"filter_query": "{change_pct} < 0", "column_id": "change_pct"},
                                        "color": "var(--danger)",
                                    },
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Panel 2: Breakdown (hidden by default)
            html.Div(
                id="market-panel-breakdown",
                style={"display": "none"},
                children=[
                    # Manual ticker input card
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div("Add Tickers", className="card-title"),
                            html.Div(
                                "Enter comma-separated tickers to append to this benchmark.",
                                className="hint-text",
                                style={"marginBottom": "10px"},
                            ),
                            dcc.Textarea(
                                id="market-breakdown-ticker-input",
                                placeholder="e.g., SOF.BR, KBC.BR, UCB.BR",
                                style={
                                    "width": "100%",
                                    "height": "80px",
                                    "padding": "10px",
                                    "fontSize": "14px",
                                    "fontFamily": "monospace",
                                },
                            ),
                            html.Button(
                                "Append",
                                id="market-breakdown-append-btn",
                                className="btn-primary",
                                style={"marginTop": "10px"},
                                n_clicks=0,
                            ),
                            html.Div(
                                id="market-breakdown-append-status",
                                style={"marginTop": "10px", "color": "var(--ok)"},
                            ),
                        ],
                    ),
                    # Tickers table card
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Tickers", className="card-title"),
                            DataTable(
                                id="market-breakdown-tickers-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Sector", "id": "sector"},
                                    {"name": "Label", "id": "fundamental_label"},
                                    {"name": "Score", "id": "bench_score_total", "type": "numeric", "format": {"specifier": ".1f"}},
                                    {"name": "Sector %ile", "id": "bench_sector_pct_total", "type": "numeric", "format": {"specifier": ".1f"}},
                                    {"name": "Confidence", "id": "bench_confidence"},
                                    {"name": "Updated", "id": "updated_at"},
                                ],
                                data=[],
                                page_size=20,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                                style_data_conditional=[
                                    {
                                        "if": {"filter_query": "{fundamental_label} = INTERESTING", "column_id": "fundamental_label"},
                                        "color": "var(--ok)",
                                    },
                                    {
                                        "if": {"filter_query": "{fundamental_label} = EXPENSIVE", "column_id": "fundamental_label"},
                                        "color": "var(--warning)",
                                    },
                                    {
                                        "if": {"filter_query": "{fundamental_label} = DOUBTFUL", "column_id": "fundamental_label"},
                                        "color": "var(--text-muted)",
                                    },
                                    {
                                        "if": {"filter_query": "{fundamental_label} = AVOID", "column_id": "fundamental_label"},
                                        "color": "var(--danger)",
                                    },
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Panel 3: Settings (hidden by default)
            html.Div(
                id="market-panel-settings",
                style={"display": "none"},
                children=[
                    # Add benchmark form
                    html.Div(
                        className="card",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div("Add Benchmark", className="card-title"),
                            html.Div(
                                className="grid-3",
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Name", className="field-label"),
                                            dcc.Input(
                                                id="market-add-name",
                                                type="text",
                                                placeholder="e.g., S&P 500",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Region", className="field-label"),
                                            dcc.Input(
                                                id="market-add-region",
                                                type="text",
                                                placeholder="e.g., US",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Ticker", className="field-label"),
                                            dcc.Input(
                                                id="market-add-ticker",
                                                type="text",
                                                placeholder="e.g., ^GSPC",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                            html.Button(
                                "Add benchmark",
                                id="market-add-btn",
                                className="btn-primary",
                                style={"marginTop": "10px"},
                                n_clicks=0,
                            ),
                        ],
                    ),
                    # Manage benchmarks table
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Manage Benchmarks", className="card-title"),
                            html.Div(
                                "Select rows and click Delete to remove benchmarks.",
                                className="hint-text",
                                style={"marginBottom": "10px"},
                            ),
                            dbc.Button(
                                "Delete selected",
                                id="market-delete-btn",
                                color="secondary",
                                size="sm",
                                style={"marginBottom": "10px"},
                                n_clicks=0,
                            ),
                            DataTable(
                                id="market-benchmarks-table",
                                columns=[
                                    {"name": "ID", "id": "benchmark_id"},
                                    {"name": "Name", "id": "name"},
                                    {"name": "Region", "id": "region"},
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Code", "id": "code"},
                                ],
                                data=[],
                                page_size=10,
                                row_selectable="multi",
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


# Callback: toggle between Overview, Breakdown, and Settings panels
@callback(
    Output("market-panel-overview", "style"),
    Output("market-panel-breakdown", "style"),
    Output("market-panel-settings", "style"),
    Output("market-nav-overview", "active"),
    Output("market-nav-breakdown", "active"),
    Output("market-nav-settings", "active"),
    Output("market-nav-overview", "style"),
    Output("market-nav-breakdown", "style"),
    Output("market-nav-settings", "style"),
    Input("market-nav-overview", "n_clicks"),
    Input("market-nav-breakdown", "n_clicks"),
    Input("market-nav-settings", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_market_panels(overview_clicks, breakdown_clicks, settings_clicks):
    from dash import ctx

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "market-nav-overview":
        return (
            {"display": "block"},
            {"display": "none"},
            {"display": "none"},
            True,
            False,
            False,
            PILL_ACTIVE_STYLE,
            PILL_INACTIVE_STYLE,
            PILL_INACTIVE_STYLE,
        )
    elif button_id == "market-nav-breakdown":
        return (
            {"display": "none"},
            {"display": "block"},
            {"display": "none"},
            False,
            True,
            False,
            PILL_INACTIVE_STYLE,
            PILL_ACTIVE_STYLE,
            PILL_INACTIVE_STYLE,
        )
    elif button_id == "market-nav-settings":
        return (
            {"display": "none"},
            {"display": "none"},
            {"display": "block"},
            False,
            False,
            True,
            PILL_INACTIVE_STYLE,
            PILL_INACTIVE_STYLE,
            PILL_ACTIVE_STYLE,
        )
    else:
        raise PreventUpdate


# Callback: load benchmarks and ensure EOD data cached on page load
@callback(
    Output("market-benchmarks-table", "data"),
    Output("market-cards-container", "children"),
    Output("market-snapshot-table", "data"),
    Output("market-status-bar", "children"),
    Input("url", "pathname"),
    Input("market-refresh-trigger", "data"),
    prevent_initial_call=False,
)
def market_load_data(pathname, refresh_trigger):
    if pathname != "/market":
        raise PreventUpdate

    benchmarks = list_benchmarks()

    if not benchmarks:
        return (
            [],
            [html.Div("No benchmarks defined. Add benchmarks in Settings.", className="card", style={"padding": "20px", "textAlign": "center", "color": "var(--text-muted)"})],
            [],
            "No benchmarks configured",
        )

    # Create benchmark cards
    cards = []
    for bm in benchmarks:
        chart = create_benchmark_chart(bm["benchmark_id"], bm["ticker"], bm["name"])
        card = html.Div(
            className="card",
            children=[
                html.Div(bm["name"], className="card-title"),
                html.Div(
                    f"{bm['region']} • {bm['ticker']}",
                    className="hint-text",
                    style={"marginBottom": "8px"},
                ),
                dcc.Graph(figure=chart, config={"displayModeBar": False}),
            ],
        )
        cards.append(card)

    # Get snapshot data
    snapshot = get_latest_snapshot_all_benchmarks()

    return (
        benchmarks,
        cards,
        snapshot,
        f"Loaded {len(benchmarks)} benchmark(s)",
    )


# Callback: add new benchmark
@callback(
    Output("market-status-bar", "children", allow_duplicate=True),
    Output("market-add-name", "value"),
    Output("market-add-region", "value"),
    Output("market-add-ticker", "value"),
    Output("market-refresh-trigger", "data", allow_duplicate=True),
    Input("market-add-btn", "n_clicks"),
    State("market-add-name", "value"),
    State("market-add-region", "value"),
    State("market-add-ticker", "value"),
    State("market-refresh-trigger", "data"),
    prevent_initial_call=True,
)
def market_add_benchmark(n_clicks, name, region, ticker, current_trigger):
    if n_clicks == 0 or not name or not region or not ticker:
        raise PreventUpdate

    try:
        benchmark_id = add_benchmark(name.strip(), region.strip(), ticker.strip())
        return (
            f"Added benchmark: {name} (ID={benchmark_id})",
            "",
            "",
            "",
            (current_trigger or 0) + 1,  # Increment to trigger refresh
        )
    except Exception as e:
        return (
            f"Error adding benchmark: {str(e)}",
            name,
            region,
            ticker,
            current_trigger,  # Don't trigger refresh on error
        )


# Callback: delete selected benchmarks
@callback(
    Output("market-status-bar", "children", allow_duplicate=True),
    Output("market-refresh-trigger", "data", allow_duplicate=True),
    Input("market-delete-btn", "n_clicks"),
    State("market-benchmarks-table", "data"),
    State("market-benchmarks-table", "selected_rows"),
    State("market-refresh-trigger", "data"),
    prevent_initial_call=True,
)
def market_delete_benchmarks(n_clicks, data, selected_rows, current_trigger):
    if n_clicks == 0 or not data or not selected_rows or len(selected_rows) == 0:
        raise PreventUpdate

    try:
        deleted_ids = []
        for idx in selected_rows:
            benchmark_id = data[idx]["benchmark_id"]
            delete_benchmark(benchmark_id)
            deleted_ids.append(benchmark_id)

        return (
            f"Deleted {len(deleted_ids)} benchmark(s)",
            (current_trigger or 0) + 1,  # Increment to trigger refresh
        )
    except Exception as e:
        return (
            f"Error deleting benchmarks: {str(e)}",
            current_trigger,  # Don't trigger refresh on error
        )


# Callback: populate breakdown benchmark dropdown
@callback(
    Output("market-breakdown-benchmark", "options"),
    Input("url", "pathname"),
    Input("market-refresh-trigger", "data"),
)
def populate_breakdown_dropdown(pathname, refresh_trigger):
    if pathname != "/market":
        raise PreventUpdate

    benchmarks = list_benchmarks()
    return [{"label": bm["name"], "value": bm["benchmark_id"]} for bm in benchmarks]


# Callback: append tickers
@callback(
    Output("market-breakdown-append-status", "children"),
    Output("market-breakdown-ticker-input", "value"),
    Output("market-breakdown-tickers-table", "data", allow_duplicate=True),
    Input("market-breakdown-append-btn", "n_clicks"),
    State("market-breakdown-benchmark", "value"),
    State("market-breakdown-ticker-input", "value"),
    prevent_initial_call=True,
)
def append_tickers(n_clicks, benchmark_id, ticker_input):
    if n_clicks == 0 or not benchmark_id or not ticker_input:
        raise PreventUpdate

    # Parse tickers: split by comma/whitespace, strip, uppercase, dedupe
    raw_tickers = ticker_input.replace("\n", ",").replace(" ", ",").split(",")
    tickers = list(set(t.strip().upper() for t in raw_tickers if t.strip()))

    if not tickers:
        return "No valid tickers provided.", ticker_input, []

    added = upsert_benchmark_tickers(benchmark_id, tickers)

    # Refresh table
    table_data = get_benchmark_tickers_with_fundamentals(benchmark_id)

    return f"Added {added} ticker(s) to benchmark.", "", table_data


# Callback: refresh fundamentals
@callback(
    Output("market-status-bar", "children", allow_duplicate=True),
    Output("market-breakdown-tickers-table", "data", allow_duplicate=True),
    Input("market-breakdown-refresh-btn", "n_clicks"),
    State("market-breakdown-benchmark", "value"),
    prevent_initial_call=True,
)
def refresh_fundamentals(n_clicks, benchmark_id):
    if n_clicks == 0:
        raise PreventUpdate

    if not benchmark_id:
        return "Please select a benchmark first.", []

    # Get all tickers for this benchmark
    tickers_data = get_benchmark_tickers_with_fundamentals(benchmark_id)
    tickers = [t["ticker"] for t in tickers_data]

    if not tickers:
        return "No tickers to refresh. Add tickers first.", tickers_data

    result = refresh_benchmark_fundamentals(benchmark_id, tickers)

    # Reload table with updated data
    updated_data = get_benchmark_tickers_with_fundamentals(benchmark_id)

    # Add status indicator for missing snapshot data
    for row in updated_data:
        if row.get("updated_at") is None:
            row["fundamental_label"] = "missing"

    total = result['succeeded'] + result['failed']
    return (
        f"Refreshed {result['succeeded']}/{total} ticker(s). {result['failed']} failed.",
        updated_data,
    )


# Callback: load breakdown table on benchmark selection
@callback(
    Output("market-breakdown-tickers-table", "data"),
    Input("market-breakdown-benchmark", "value"),
)
def load_breakdown_tickers(benchmark_id):
    if not benchmark_id:
        return []

    data = get_benchmark_tickers_with_fundamentals(benchmark_id)

    # Mark rows without snapshot data as "missing"
    for row in data:
        if row.get("updated_at") is None:
            row["fundamental_label"] = "missing"

    return data
