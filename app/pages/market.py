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

            # Panel 2: Settings (hidden by default)
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


# Callback: toggle between Overview and Settings panels
@callback(
    Output("market-panel-overview", "style"),
    Output("market-panel-settings", "style"),
    Output("market-nav-overview", "active"),
    Output("market-nav-settings", "active"),
    Output("market-nav-overview", "style"),
    Output("market-nav-settings", "style"),
    Input("market-nav-overview", "n_clicks"),
    Input("market-nav-settings", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_market_panels(overview_clicks, settings_clicks):
    from dash import ctx

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "market-nav-overview":
        return (
            {"display": "block"},
            {"display": "none"},
            True,
            False,
            PILL_ACTIVE_STYLE,
            PILL_INACTIVE_STYLE,
        )
    elif button_id == "market-nav-settings":
        return (
            {"display": "none"},
            {"display": "block"},
            False,
            True,
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
