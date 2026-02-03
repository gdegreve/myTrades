"""Portfolio Overview page - read-only state & KPIs.

Displays portfolio performance metrics, charts, and top contributors.
All data is computed from transactions + price_bars (no snapshot tables).
"""
from __future__ import annotations

import numpy as np
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import base64
from datetime import date as dt_date

from app.db.portfolio_repo import list_portfolios
from app.db.overview_repo import (
    get_portfolio_summary,
    get_current_positions,
    get_latest_prices,
    get_previous_prices,
    get_price_history,
    get_sector_allocations,
    get_latest_eod_date,
    get_price_data_coverage,
    get_all_portfolios_summary,
    get_all_current_positions,
    get_all_sector_allocations,
    get_daily_cashflows,
    upsert_intraday_prices,
    get_intraday_prices,
)


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
            # Page header
            html.Div(
                className="page-header",
                children=[
                    html.Div(
                        children=[
                            html.H2("Portfolio - Overview", style={"margin": "0"}),
                            html.Div(
                                id="overview-eod-date",
                                className="page-subtitle",
                            ),
                        ]
                    ),
                    html.Div(
                        id="overview-dropdown-container",
                        className="page-header-actions",
                        style={"display": "none"},
                        children=[
                            html.Div(
                                children=[
                                    html.Div("Portfolio", className="field-label"),
                                    dcc.Dropdown(
                                        id="overview-portfolio",
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

            # Nav pills for 2 tabs
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
                                id="overview-nav-overview",
                                active=True,
                                style=PILL_ACTIVE_STYLE,
                            ),
                            dbc.NavLink(
                                "Breakdown",
                                id="overview-nav-breakdown",
                                active=False,
                                style=PILL_INACTIVE_STYLE,
                            ),
                        ],
                    ),
                ],
            ),

            # =================================================================
            # PANEL 1: Overview - aggregated across ALL portfolios (visible by default)
            # =================================================================
            html.Div(
                id="overview-panel-overview",
                style={"display": "block"},
                children=[
                    # Warning banner for insufficient data
                    html.Div(id="agg-data-warning", style={"marginBottom": "14px"}),

                    # KPI Cards Row 1 (3 columns)
                    html.Div(
                        className="grid-3",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Total Portfolio Value", className="card-title"),
                                    html.Div(
                                        id="agg-kpi-total-value",
                                        children="€0.00",
                                        style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                    html.Div(
                                        id="agg-kpi-total-value-change",
                                        className="hint-text",
                                        style={"marginTop": "6px"},
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Total Return", className="card-title"),
                                    html.Div(
                                        id="agg-kpi-total-return",
                                        children="0.00%",
                                        style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                    html.Div("Since inception", className="hint-text", style={"marginTop": "6px"}),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Benchmark Delta", className="card-title"),
                                    html.Div(
                                        id="agg-kpi-benchmark-delta",
                                        children="N/A",
                                        style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                    html.Div(
                                        id="agg-kpi-benchmark-name",
                                        className="hint-text",
                                        style={"marginTop": "6px"},
                                    ),
                                ],
                            ),
                        ],
                    ),

                    # KPI Cards Row 2 (3 columns)
                    html.Div(
                        className="grid-3",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Sharpe Ratio", className="card-title"),
                                    html.Div(
                                        id="agg-kpi-sharpe",
                                        children="N/A",
                                        style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                    html.Div("Annualized (rf=0)", className="hint-text", style={"marginTop": "6px"}),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Max Drawdown", className="card-title"),
                                    html.Div(
                                        id="agg-kpi-max-drawdown",
                                        children="0.00%",
                                        style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                    html.Div("Peak to trough", className="hint-text", style={"marginTop": "6px"}),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Cash Allocation", className="card-title"),
                                    html.Div(
                                        id="agg-kpi-cash-pct",
                                        children="0.00%",
                                        style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                                    ),
                                    html.Div(
                                        id="agg-kpi-cash-amount",
                                        className="hint-text",
                                        style={"marginTop": "6px"},
                                    ),
                                ],
                            ),
                        ],
                    ),

                    # Charts Row 1 (2 columns)
                    html.Div(
                        className="grid-2",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Portfolio vs Benchmark", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="agg-chart-returns", config={"displayModeBar": False}),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Drawdown", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="agg-chart-drawdown", config={"displayModeBar": False}),
                                ],
                            ),
                        ],
                    ),

                    # Charts Row 2 (2 columns)
                    html.Div(
                        className="grid-2",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Cash vs Invested", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="agg-chart-cash-donut", config={"displayModeBar": False}),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Sector Allocation", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="agg-chart-sectors", config={"displayModeBar": False}),
                                ],
                            ),
                        ],
                    ),

                    # Top Contributors Table
                    html.Div(
                        className="card",
                        children=[
                            html.Div(
                                className="card-title-row",
                                children=[
                                    html.Div("Contributors (Day P/L)", className="card-title"),
                                    html.Div("All positions sorted by absolute daily change", className="hint-text"),
                                ],
                            ),
                            DataTable(
                                id="agg-contributors-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Shares", "id": "shares", "type": "numeric"},
                                    {"name": "Prev Price", "id": "prev_price", "type": "numeric"},
                                    {"name": "Curr Price", "id": "curr_price", "type": "numeric"},
                                    {"name": "Daily P/L", "id": "daily_pnl", "type": "numeric"},
                                    {"name": "Daily %", "id": "daily_pct", "type": "numeric"},
                                    {"name": "Trend", "id": "trend", "presentation": "markdown"},
                                ],
                                data=[],
                                sort_action="native",
                                page_size=10,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                                style_data_conditional=[
                                    {
                                        "if": {
                                            "filter_query": "{daily_pnl} > 0",
                                            "column_id": "daily_pnl"
                                        },
                                        "color": "#28a745",
                                    },
                                    {
                                        "if": {
                                            "filter_query": "{daily_pnl} < 0",
                                            "column_id": "daily_pnl"
                                        },
                                        "color": "#dc3545",
                                    },
                                    {
                                        "if": {
                                            "filter_query": "{daily_pct} > 0",
                                            "column_id": "daily_pct"
                                        },
                                        "color": "#28a745",
                                    },
                                    {
                                        "if": {
                                            "filter_query": "{daily_pct} < 0",
                                            "column_id": "daily_pct"
                                        },
                                        "color": "#dc3545",
                                    },
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # =================================================================
            # PANEL 2: Breakdown - per-portfolio view (hidden by default)
            # =================================================================
            html.Div(
                id="overview-panel-breakdown",
                style={"display": "none"},
                children=[
                    # Warning banner for insufficient data
                    html.Div(id="overview-data-warning", style={"marginBottom": "14px"}),

                    # KPI Cards Row 1 (3 columns)
            html.Div(
                className="grid-3",
                style={"marginBottom": "14px"},
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Total Portfolio Value", className="card-title"),
                            html.Div(
                                id="overview-kpi-total-value",
                                children="€0.00",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div(
                                id="overview-kpi-total-value-change",
                                className="hint-text",
                                style={"marginTop": "6px"},
                            ),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Total Return", className="card-title"),
                            html.Div(
                                id="overview-kpi-total-return",
                                children="0.00%",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div("Since inception", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Benchmark Delta", className="card-title"),
                            html.Div(
                                id="overview-kpi-benchmark-delta",
                                children="N/A",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div(
                                id="overview-kpi-benchmark-name",
                                className="hint-text",
                                style={"marginTop": "6px"},
                            ),
                        ],
                    ),
                ],
            ),

            # KPI Cards Row 2 (3 columns)
            html.Div(
                className="grid-3",
                style={"marginBottom": "14px"},
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Sharpe Ratio", className="card-title"),
                            html.Div(
                                id="overview-kpi-sharpe",
                                children="N/A",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div("Annualized (rf=0)", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Max Drawdown", className="card-title"),
                            html.Div(
                                id="overview-kpi-max-drawdown",
                                children="0.00%",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div("Peak to trough", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Cash Allocation", className="card-title"),
                            html.Div(
                                id="overview-kpi-cash-pct",
                                children="0.00%",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div(
                                id="overview-kpi-cash-amount",
                                className="hint-text",
                                style={"marginTop": "6px"},
                            ),
                        ],
                    ),
                ],
            ),

            # Charts Row 1 (2 columns)
            html.Div(
                className="grid-2",
                style={"marginBottom": "14px"},
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Portfolio vs Benchmark", className="card-title", style={"marginBottom": "10px"}),
                            dcc.Graph(id="overview-chart-returns", config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Drawdown", className="card-title", style={"marginBottom": "10px"}),
                            dcc.Graph(id="overview-chart-drawdown", config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),

            # Charts Row 2 (2 columns)
            html.Div(
                className="grid-2",
                style={"marginBottom": "14px"},
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Cash vs Invested", className="card-title", style={"marginBottom": "10px"}),
                            dcc.Graph(id="overview-chart-cash-donut", config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Sector Allocation", className="card-title", style={"marginBottom": "10px"}),
                            dcc.Graph(id="overview-chart-sectors", config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),

            # Top Contributors Table
            html.Div(
                className="card",
                children=[
                    html.Div(
                        className="card-title-row",
                        children=[
                            html.Div("Contributors (Day P/L)", className="card-title"),
                            html.Div("All positions sorted by absolute daily change", className="hint-text"),
                        ],
                    ),
                    DataTable(
                        id="overview-contributors-table",
                        columns=[
                            {"name": "Ticker", "id": "ticker"},
                            {"name": "Shares", "id": "shares", "type": "numeric"},
                            {"name": "Prev Price", "id": "prev_price", "type": "numeric"},
                            {"name": "Curr Price", "id": "curr_price", "type": "numeric"},
                            {"name": "Daily P/L", "id": "daily_pnl", "type": "numeric"},
                            {"name": "Daily %", "id": "daily_pct", "type": "numeric"},
                            {"name": "Total P/L %", "id": "total_pnl_pct", "type": "numeric"},
                            {"name": "Trend", "id": "trend", "presentation": "markdown"},
                        ],
                        data=[],
                        sort_action="native",
                        page_size=10,
                        style_table={"overflowX": "auto"},
                        style_cell={"padding": "10px", "textAlign": "left"},
                        style_header={"fontWeight": "600"},
                        style_data_conditional=[
                            {
                                "if": {
                                    "filter_query": "{daily_pnl} > 0",
                                    "column_id": "daily_pnl"
                                },
                                "color": "#28a745",
                            },
                            {
                                "if": {
                                    "filter_query": "{daily_pnl} < 0",
                                    "column_id": "daily_pnl"
                                },
                                "color": "#dc3545",
                            },
                            {
                                "if": {
                                    "filter_query": "{daily_pct} > 0",
                                    "column_id": "daily_pct"
                                },
                                "color": "#28a745",
                            },
                            {
                                "if": {
                                    "filter_query": "{daily_pct} < 0",
                                    "column_id": "daily_pct"
                                },
                                "color": "#dc3545",
                            },
                            {
                                "if": {
                                    "filter_query": "{total_pnl_pct} > 0",
                                    "column_id": "total_pnl_pct"
                                },
                                "color": "#28a745",
                            },
                            {
                                "if": {
                                    "filter_query": "{total_pnl_pct} < 0",
                                    "column_id": "total_pnl_pct"
                                },
                                "color": "#dc3545",
                            },
                        ],
                    ),
                ],
            ),
                ],
            ),
        ],
        style={"maxWidth": "1100px"},
    )


def _create_empty_figure(message: str = "No data available") -> go.Figure:
    """Create an empty figure with a centered message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=14, color="rgba(255,255,255,0.5)"),
    )
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0),
        height=280,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _apply_chart_theme(fig: go.Figure) -> None:
    """Apply consistent dark theme to chart."""
    fig.update_layout(
        font=dict(color="rgba(255,255,255,0.9)", size=12),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        height=280,
    )
    fig.update_xaxes(
        showgrid=False,
        tickfont=dict(color="rgba(255,255,255,0.8)"),
    )
    fig.update_yaxes(
        showgrid=False,
        tickfont=dict(color="rgba(255,255,255,0.8)"),
    )


@callback(
    Output("overview-portfolio", "options"),
    Output("overview-portfolio", "value"),
    Input("url", "pathname"),
)
def populate_portfolio_dropdown(pathname):
    """Populate portfolio dropdown on page load."""
    if pathname not in ("/portfolio/overview", "/"):
        raise PreventUpdate
    portfolios = list_portfolios()
    if not portfolios:
        return [], None
    options = [{"label": p["name"], "value": p["id"]} for p in portfolios]
    return options, portfolios[0]["id"]


@callback(
    Output("overview-panel-overview", "style"),
    Output("overview-panel-breakdown", "style"),
    Output("overview-nav-overview", "active"),
    Output("overview-nav-breakdown", "active"),
    Output("overview-nav-overview", "style"),
    Output("overview-nav-breakdown", "style"),
    Output("overview-dropdown-container", "style"),
    Input("overview-nav-overview", "n_clicks"),
    Input("overview-nav-breakdown", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_overview_panels(overview_clicks, breakdown_clicks):
    """Toggle between Overview and Breakdown panels based on pill clicks."""
    from dash import ctx

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Default: all hidden, all inactive
    panel_styles = {
        "overview": {"display": "none"},
        "breakdown": {"display": "none"},
    }
    active_states = {
        "overview": False,
        "breakdown": False,
    }
    pill_styles = {
        "overview": PILL_INACTIVE_STYLE,
        "breakdown": PILL_INACTIVE_STYLE,
    }
    dropdown_style = {"display": "none"}

    # Determine which tab was clicked
    if button_id == "overview-nav-overview":
        panel_styles["overview"] = {"display": "block"}
        active_states["overview"] = True
        pill_styles["overview"] = PILL_ACTIVE_STYLE
    elif button_id == "overview-nav-breakdown":
        panel_styles["breakdown"] = {"display": "block"}
        active_states["breakdown"] = True
        pill_styles["breakdown"] = PILL_ACTIVE_STYLE
        dropdown_style = {"display": "block"}
    else:
        raise PreventUpdate

    return (
        panel_styles["overview"],
        panel_styles["breakdown"],
        active_states["overview"],
        active_states["breakdown"],
        pill_styles["overview"],
        pill_styles["breakdown"],
        dropdown_style,
    )


@callback(
    Output("overview-data-warning", "children"),
    Output("overview-kpi-total-value", "children"),
    Output("overview-kpi-total-value-change", "children"),
    Output("overview-kpi-total-return", "children"),
    Output("overview-kpi-benchmark-delta", "children"),
    Output("overview-kpi-benchmark-name", "children"),
    Output("overview-kpi-sharpe", "children"),
    Output("overview-kpi-max-drawdown", "children"),
    Output("overview-kpi-cash-pct", "children"),
    Output("overview-kpi-cash-amount", "children"),
    Output("overview-chart-returns", "figure"),
    Output("overview-chart-drawdown", "figure"),
    Output("overview-chart-cash-donut", "figure"),
    Output("overview-chart-sectors", "figure"),
    Output("overview-contributors-table", "data"),
    Input("overview-portfolio", "value"),
)
def refresh_overview_data(portfolio_id):
    """Main callback: fetch data, compute metrics, render all outputs."""
    if portfolio_id is None:
        raise PreventUpdate

    # Check data coverage
    data_coverage = get_price_data_coverage()
    data_warning = None
    if data_coverage < 30:
        data_warning = dbc.Alert(
            f"Limited price history ({data_coverage} days). Performance metrics may be inaccurate. "
            "Consider backfilling historical prices.",
            color="warning",
            dismissable=True,
        )

    # Get portfolio summary
    summary = get_portfolio_summary(portfolio_id)
    cash_balance = summary["cash_balance"]
    benchmark_ticker = summary["benchmark_ticker"]
    total_invested = summary["total_invested"]

    # Get current positions
    positions = get_current_positions(portfolio_id)
    position_tickers = [p["ticker"] for p in positions]

    # Get latest and previous prices
    all_tickers = position_tickers.copy()
    if benchmark_ticker:
        all_tickers.append(benchmark_ticker)

    latest_prices = get_latest_prices(all_tickers)
    previous_prices = get_previous_prices(all_tickers)

    # Compute market values
    position_values = {}
    market_value_total = 0.0
    prev_market_value_total = 0.0

    for p in positions:
        ticker = p["ticker"]
        shares = p["shares"]

        if ticker in latest_prices:
            curr_value = shares * latest_prices[ticker]
            position_values[ticker] = curr_value
            market_value_total += curr_value

        if ticker in previous_prices:
            prev_value = shares * previous_prices[ticker]
            prev_market_value_total += prev_value

    # Total portfolio value
    total_value = cash_balance + market_value_total
    prev_total_value = cash_balance + prev_market_value_total

    # Format Total Value KPI
    total_value_str = f"€{total_value:,.2f}"

    # Daily change
    if prev_total_value > 0:
        daily_change_pct = ((total_value - prev_total_value) / prev_total_value) * 100
        change_color = "#28a745" if daily_change_pct >= 0 else "#dc3545"
        change_sign = "+" if daily_change_pct >= 0 else ""
        total_value_change = html.Span(
            f"{change_sign}{daily_change_pct:.2f}% vs prev EOD",
            style={"color": change_color},
        )
    else:
        total_value_change = "Cash + market value"

    # Total Return %
    if total_invested > 0:
        total_return_pct = ((total_value - total_invested) / total_invested) * 100
        return_color = "#28a745" if total_return_pct >= 0 else "#dc3545"
        return_sign = "+" if total_return_pct >= 0 else ""
        total_return_str = html.Span(
            f"{return_sign}{total_return_pct:.2f}%",
            style={"color": return_color},
        )
    else:
        total_return_str = "N/A"

    # Benchmark Delta (simplified - compare current portfolio return vs benchmark)
    benchmark_delta_str = "N/A"
    benchmark_name_str = "No benchmark set"

    if benchmark_ticker and benchmark_ticker in latest_prices:
        benchmark_name_str = f"vs {benchmark_ticker}"
        # For now, show simple comparison based on available data
        # Full historical comparison would need more price history
        if data_coverage >= 2 and benchmark_ticker in previous_prices:
            bench_curr = latest_prices[benchmark_ticker]
            bench_prev = previous_prices[benchmark_ticker]
            bench_return = ((bench_curr - bench_prev) / bench_prev) * 100 if bench_prev > 0 else 0

            if prev_total_value > 0:
                portfolio_day_return = ((total_value - prev_total_value) / prev_total_value) * 100
                delta = portfolio_day_return - bench_return
                delta_color = "#28a745" if delta >= 0 else "#dc3545"
                delta_sign = "+" if delta >= 0 else ""
                benchmark_delta_str = html.Span(
                    f"{delta_sign}{delta:.2f}%",
                    style={"color": delta_color},
                )
            else:
                benchmark_delta_str = "N/A"

    # Sharpe Ratio (need historical data)
    sharpe_str = "N/A"
    max_drawdown_str = "0.00%"

    # Get price history for time series metrics
    if position_tickers and data_coverage >= 5:
        price_history = get_price_history(position_tickers + ([benchmark_ticker] if benchmark_ticker else []))

        # Build portfolio value time series (simplified)
        # Get all unique dates across all tickers
        all_dates = set()
        for ticker_data in price_history.values():
            for point in ticker_data:
                all_dates.add(point["date"])

        if all_dates:
            sorted_dates = sorted(all_dates)
            portfolio_values = []

            for day in sorted_dates:
                day_value = cash_balance
                for p in positions:
                    ticker = p["ticker"]
                    shares = p["shares"]
                    # Find price for this ticker on this date
                    ticker_prices = {pt["date"]: pt["close"] for pt in price_history.get(ticker, [])}
                    if day in ticker_prices:
                        day_value += shares * ticker_prices[day]
                    elif ticker_prices:
                        # Use most recent available price before this date
                        available = [p_day for p_day in ticker_prices.keys() if p_day <= day]
                        if available:
                            day_value += shares * ticker_prices[max(available)]

                if day_value > 0:
                    portfolio_values.append(day_value)

            if len(portfolio_values) >= 2:
                values = np.array(portfolio_values)

                # Calculate daily returns with TWR cashflow neutralization
                # r_t = (V_t - V_{t-1} - NetCashFlow_t) / V_{t-1}
                cashflows = get_daily_cashflows(portfolio_id)
                daily_returns = []
                for i in range(1, len(values)):
                    day = sorted_dates[i]
                    net_cf = cashflows.get(day, 0.0)
                    prev_val = values[i - 1]
                    if prev_val > 0:
                        r = (values[i] - prev_val - net_cf) / prev_val
                        daily_returns.append(r)
                daily_returns = np.array(daily_returns) if daily_returns else np.array([])

                # Sharpe Ratio (annualized, rf=0)
                if len(daily_returns) >= 5:
                    mean_return = np.mean(daily_returns)
                    std_return = np.std(daily_returns, ddof=1)
                    if std_return > 0:
                        sharpe = (mean_return / std_return) * np.sqrt(252)
                        sharpe_color = "#28a745" if sharpe >= 0 else "#dc3545"
                        sharpe_str = html.Span(
                            f"{sharpe:.2f}",
                            style={"color": sharpe_color},
                        )

                # Max Drawdown
                running_max = np.maximum.accumulate(values)
                drawdowns = (values - running_max) / running_max * 100
                max_dd = np.min(drawdowns)
                max_drawdown_str = html.Span(
                    f"{max_dd:.2f}%",
                    style={"color": "#dc3545" if max_dd < -5 else "#ffc107" if max_dd < 0 else "#28a745"},
                )

    # Cash Allocation %
    if total_value > 0:
        cash_pct = (cash_balance / total_value) * 100
        cash_pct_str = f"{cash_pct:.1f}%"
    else:
        cash_pct_str = "N/A"
    cash_amount_str = f"€{cash_balance:,.2f}"

    # ========== CHARTS ==========

    # Chart 1: Portfolio vs Benchmark (Return Index)
    returns_fig = _create_empty_figure("Insufficient price history")

    if position_tickers and data_coverage >= 2:
        price_history = get_price_history(position_tickers + ([benchmark_ticker] if benchmark_ticker else []))

        all_dates = set()
        for ticker_data in price_history.values():
            for point in ticker_data:
                all_dates.add(point["date"])

        if all_dates:
            sorted_dates = sorted(all_dates)
            portfolio_values = []

            for day in sorted_dates:
                day_value = cash_balance
                for p in positions:
                    ticker = p["ticker"]
                    shares = p["shares"]
                    ticker_prices = {pt["date"]: pt["close"] for pt in price_history.get(ticker, [])}
                    if day in ticker_prices:
                        day_value += shares * ticker_prices[day]
                    elif ticker_prices:
                        available = [p_day for p_day in ticker_prices.keys() if p_day <= day]
                        if available:
                            day_value += shares * ticker_prices[max(available)]

                portfolio_values.append(day_value)

            if len(portfolio_values) >= 2 and portfolio_values[0] > 0:
                # Normalize to 100
                base_value = portfolio_values[0]
                indexed_values = [(v / base_value) * 100 for v in portfolio_values]

                returns_fig = go.Figure()
                returns_fig.add_trace(go.Scatter(
                    x=sorted_dates,
                    y=indexed_values,
                    mode="lines",
                    name="Portfolio",
                    line=dict(color="#2D7DFF", width=2),
                ))

                # Add benchmark if available
                if benchmark_ticker and benchmark_ticker in price_history:
                    bench_data = price_history[benchmark_ticker]
                    if len(bench_data) >= 2:
                        bench_dates = [pt["date"] for pt in bench_data]
                        bench_closes = [pt["close"] for pt in bench_data]
                        bench_base = bench_closes[0]
                        bench_indexed = [(c / bench_base) * 100 for c in bench_closes]

                        returns_fig.add_trace(go.Scatter(
                            x=bench_dates,
                            y=bench_indexed,
                            mode="lines",
                            name=benchmark_ticker,
                            line=dict(color="#32C5FF", width=2, dash="dot"),
                        ))

                returns_fig.update_layout(
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                        font=dict(color="rgba(255,255,255,0.8)"),
                    ),
                    yaxis_title="Index (100 = start)",
                )
                _apply_chart_theme(returns_fig)

    # Chart 2: Drawdown
    drawdown_fig = _create_empty_figure("Insufficient price history")

    if position_tickers and data_coverage >= 2:
        price_history = get_price_history(position_tickers)

        all_dates = set()
        for ticker_data in price_history.values():
            for point in ticker_data:
                all_dates.add(point["date"])

        if all_dates:
            sorted_dates = sorted(all_dates)
            portfolio_values = []

            for day in sorted_dates:
                day_value = cash_balance
                for p in positions:
                    ticker = p["ticker"]
                    shares = p["shares"]
                    ticker_prices = {pt["date"]: pt["close"] for pt in price_history.get(ticker, [])}
                    if day in ticker_prices:
                        day_value += shares * ticker_prices[day]
                    elif ticker_prices:
                        available = [p_day for p_day in ticker_prices.keys() if p_day <= day]
                        if available:
                            day_value += shares * ticker_prices[max(available)]

                portfolio_values.append(day_value)

            if len(portfolio_values) >= 2:
                values = np.array(portfolio_values)
                running_max = np.maximum.accumulate(values)
                drawdowns = (values - running_max) / running_max * 100

                drawdown_fig = go.Figure()
                drawdown_fig.add_trace(go.Scatter(
                    x=sorted_dates,
                    y=drawdowns.tolist(),
                    mode="lines",
                    fill="tozeroy",
                    name="Drawdown",
                    line=dict(color="#dc3545", width=1),
                    fillcolor="rgba(220,53,69,0.3)",
                ))
                drawdown_fig.update_layout(yaxis_title="Drawdown %")
                _apply_chart_theme(drawdown_fig)

    # Chart 3: Cash vs Invested (Donut)
    invested_value = market_value_total

    if total_value > 0:
        cash_donut_fig = go.Figure()
        cash_donut_fig.add_trace(go.Pie(
            values=[cash_balance, invested_value],
            labels=["Cash", "Invested"],
            hole=0.6,
            marker=dict(colors=["#32C5FF", "#2D7DFF"]),
            textinfo="label+percent",
            textfont=dict(color="white"),
            hovertemplate="<b>%{label}</b><br>€%{value:,.2f}<br>%{percent}<extra></extra>",
        ))
        cash_donut_fig.update_layout(
            showlegend=False,
            annotations=[
                dict(
                    text=f"€{total_value:,.0f}",
                    x=0.5, y=0.5,
                    font=dict(size=18, color="white"),
                    showarrow=False,
                )
            ],
        )
        _apply_chart_theme(cash_donut_fig)
    else:
        cash_donut_fig = _create_empty_figure("No portfolio value")

    # Chart 4: Sector Allocation (Horizontal Bar)
    sector_data = get_sector_allocations(portfolio_id, position_values)

    if sector_data:
        # Sort by percentage descending
        sector_data.sort(key=lambda x: x["percentage"], reverse=True)

        sectors_fig = go.Figure()
        sectors_fig.add_trace(go.Bar(
            x=[s["percentage"] for s in sector_data],
            y=[s["sector"] for s in sector_data],
            orientation="h",
            marker=dict(color="#2D7DFF"),
            text=[f"{s['percentage']:.1f}%" for s in sector_data],
            textposition="auto",
            textfont=dict(color="white"),
        ))
        sectors_fig.update_layout(
            xaxis_title="Allocation %",
            yaxis=dict(autorange="reversed"),
        )
        _apply_chart_theme(sectors_fig)
    else:
        sectors_fig = _create_empty_figure("No sector data")

    # ========== TOP CONTRIBUTORS TABLE ==========
    # First, get cost basis data for each position
    from app.db.connection import get_connection
    cost_basis_map = {}

    with get_connection() as conn:
        for p in positions:
            ticker = p["ticker"]
            # Calculate cost basis with and without commission
            rows = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN transaction_type = 'buy' THEN shares * price ELSE 0 END) as cost_no_comm,
                    SUM(CASE WHEN transaction_type = 'buy' THEN commission ELSE 0 END) as total_commission
                FROM transactions
                WHERE portfolio_id = ? AND ticker = ?
                """,
                (portfolio_id, ticker)
            ).fetchone()

            if rows:
                cost_no_comm = rows["cost_no_comm"] or 0.0
                total_commission = rows["total_commission"] or 0.0
                cost_with_comm = cost_no_comm + total_commission

                cost_basis_map[ticker] = {
                    "cost_no_comm": cost_no_comm,
                    "cost_with_comm": cost_with_comm,
                }

    contributors_data = []

    for p in positions:
        ticker = p["ticker"]
        shares = p["shares"]

        if ticker in latest_prices and ticker in previous_prices:
            curr_price = latest_prices[ticker]
            prev_price = previous_prices[ticker]
            daily_pnl = shares * (curr_price - prev_price)
            daily_pct = ((curr_price - prev_price) / prev_price) * 100 if prev_price > 0 else 0

            # Calculate all-time P/L % (with commission)
            total_pnl_pct = 0.0

            if ticker in cost_basis_map:
                cost_data = cost_basis_map[ticker]
                current_value = shares * curr_price

                # P/L % with commission (true cost basis)
                if cost_data["cost_with_comm"] > 0:
                    total_pnl_pct = ((current_value - cost_data["cost_with_comm"]) / cost_data["cost_with_comm"]) * 100

            contributors_data.append({
                "ticker": ticker,
                "shares": round(shares, 2),
                "prev_price": round(prev_price, 2),
                "curr_price": round(curr_price, 2),
                "daily_pnl": round(daily_pnl, 2),
                "daily_pct": round(daily_pct, 2),
                "total_pnl_pct": round(total_pnl_pct, 2),
            })

    # Sort by absolute P/L (show all, no top-5 limit)
    contributors_data.sort(key=lambda x: abs(x["daily_pnl"]), reverse=True)

    # Fetch intraday data for sparklines
    today_str = dt_date.today().isoformat()
    intraday_cache = get_intraday_prices(position_tickers, today_str)

    # Try to fetch fresh intraday data for tickers that don't have cached data
    tickers_to_fetch = [t for t in position_tickers if not intraday_cache.get(t)]
    if tickers_to_fetch:
        try:
            # Bulk fetch intraday data from yfinance
            intraday_data = yf.download(tickers_to_fetch, period="1d", interval="5m", group_by="ticker", progress=False)

            for ticker in tickers_to_fetch:
                bars = []
                try:
                    if len(tickers_to_fetch) == 1:
                        ticker_data = intraday_data
                    else:
                        ticker_data = intraday_data[ticker]

                    if not ticker_data.empty:
                        for idx, row in ticker_data.iterrows():
                            if not np.isnan(row.get('Close', np.nan)):
                                bars.append({
                                    "ts": int(idx.timestamp()),
                                    "price": float(row['Close']),
                                })
                except (KeyError, AttributeError):
                    pass

                if bars:
                    upsert_intraday_prices(ticker, today_str, bars)
                    intraday_cache[ticker] = bars
        except Exception:
            pass  # Silently handle yfinance failures

    # Add sparkline to each row
    for row in contributors_data:
        ticker = row["ticker"]
        pos = row["daily_pnl"]
        bars = intraday_cache.get(ticker, [])
        if bars and len(bars) >= 2:
            last_ts = bars[-1]["ts"]
            row["trend"] = f"![t](/sparkline/{ticker}?day={today_str}&pos={pos}&ts={last_ts})"
        else:
            row["trend"] = ""

    return (
        data_warning,
        total_value_str,
        total_value_change,
        total_return_str,
        benchmark_delta_str,
        benchmark_name_str,
        sharpe_str,
        max_drawdown_str,
        cash_pct_str,
        cash_amount_str,
        returns_fig,
        drawdown_fig,
        cash_donut_fig,
        sectors_fig,
        contributors_data,
    )


@callback(
    Output("overview-eod-date", "children"),
    Output("agg-data-warning", "children"),
    Output("agg-kpi-total-value", "children"),
    Output("agg-kpi-total-value-change", "children"),
    Output("agg-kpi-total-return", "children"),
    Output("agg-kpi-benchmark-delta", "children"),
    Output("agg-kpi-benchmark-name", "children"),
    Output("agg-kpi-sharpe", "children"),
    Output("agg-kpi-max-drawdown", "children"),
    Output("agg-kpi-cash-pct", "children"),
    Output("agg-kpi-cash-amount", "children"),
    Output("agg-chart-returns", "figure"),
    Output("agg-chart-drawdown", "figure"),
    Output("agg-chart-cash-donut", "figure"),
    Output("agg-chart-sectors", "figure"),
    Output("agg-contributors-table", "data"),
    Input("url", "pathname"),
)
def refresh_aggregated_overview(pathname):
    """Main callback for Overview tab: aggregate across ALL portfolios."""
    if pathname not in ("/portfolio/overview", "/"):
        raise PreventUpdate

    # Get latest EOD date
    latest_date = get_latest_eod_date()
    eod_text = f"As of: {latest_date} EOD" if latest_date else "No price data"

    # Check data coverage
    data_coverage = get_price_data_coverage()
    data_warning = None
    if data_coverage < 30:
        data_warning = dbc.Alert(
            f"Limited price history ({data_coverage} days). Performance metrics may be inaccurate. "
            "Consider backfilling historical prices.",
            color="warning",
            dismissable=True,
        )

    # Get aggregated summary across all portfolios
    agg_summary = get_all_portfolios_summary()
    total_cash_balance = agg_summary["total_cash_balance"]
    total_invested = agg_summary["total_invested"]

    # Get all current positions across all portfolios
    all_positions = get_all_current_positions()
    position_tickers = list(set(p["ticker"] for p in all_positions))

    # Aggregate shares by ticker
    ticker_shares = {}
    for p in all_positions:
        ticker = p["ticker"]
        ticker_shares[ticker] = ticker_shares.get(ticker, 0.0) + p["shares"]

    # Get latest and previous prices
    latest_prices = get_latest_prices(position_tickers)
    previous_prices = get_previous_prices(position_tickers)

    # Compute market values
    position_values = {}
    market_value_total = 0.0
    prev_market_value_total = 0.0

    for ticker, shares in ticker_shares.items():
        if ticker in latest_prices:
            curr_value = shares * latest_prices[ticker]
            position_values[ticker] = curr_value
            market_value_total += curr_value

        if ticker in previous_prices:
            prev_value = shares * previous_prices[ticker]
            prev_market_value_total += prev_value

    # Total portfolio value
    total_value = total_cash_balance + market_value_total
    prev_total_value = total_cash_balance + prev_market_value_total

    # Format Total Value KPI
    total_value_str = f"€{total_value:,.2f}"

    # Daily change
    if prev_total_value > 0:
        daily_change_pct = ((total_value - prev_total_value) / prev_total_value) * 100
        change_color = "#28a745" if daily_change_pct >= 0 else "#dc3545"
        change_sign = "+" if daily_change_pct >= 0 else ""
        total_value_change = html.Span(
            f"{change_sign}{daily_change_pct:.2f}% vs prev EOD",
            style={"color": change_color},
        )
    else:
        total_value_change = "Cash + market value"

    # Total Return %
    if total_invested > 0:
        total_return_pct = ((total_value - total_invested) / total_invested) * 100
        return_color = "#28a745" if total_return_pct >= 0 else "#dc3545"
        return_sign = "+" if total_return_pct >= 0 else ""
        total_return_str = html.Span(
            f"{return_sign}{total_return_pct:.2f}%",
            style={"color": return_color},
        )
    else:
        total_return_str = "N/A"

    # Benchmark Delta (simplified - N/A for aggregated view)
    benchmark_delta_str = "N/A"
    benchmark_name_str = "Multiple portfolios"

    # Sharpe Ratio and Max Drawdown (need historical data)
    sharpe_str = "N/A"
    max_drawdown_str = "0.00%"

    # Get price history for time series metrics
    if position_tickers and data_coverage >= 5:
        price_history = get_price_history(position_tickers)

        # Build portfolio value time series
        all_dates = set()
        for ticker_data in price_history.values():
            for point in ticker_data:
                all_dates.add(point["date"])

        if all_dates:
            sorted_dates = sorted(all_dates)
            portfolio_values = []

            for day in sorted_dates:
                day_value = total_cash_balance
                for ticker, shares in ticker_shares.items():
                    ticker_prices = {pt["date"]: pt["close"] for pt in price_history.get(ticker, [])}
                    if day in ticker_prices:
                        day_value += shares * ticker_prices[day]
                    elif ticker_prices:
                        available = [p_day for p_day in ticker_prices.keys() if p_day <= day]
                        if available:
                            day_value += shares * ticker_prices[max(available)]

                if day_value > 0:
                    portfolio_values.append(day_value)

            if len(portfolio_values) >= 2:
                values = np.array(portfolio_values)

                # Calculate daily returns with TWR cashflow neutralization
                # r_t = (V_t - V_{t-1} - NetCashFlow_t) / V_{t-1}
                # For aggregated view, use None to get cashflows across all portfolios
                cashflows = get_daily_cashflows(None)
                daily_returns = []
                for i in range(1, len(values)):
                    day = sorted_dates[i]
                    net_cf = cashflows.get(day, 0.0)
                    prev_val = values[i - 1]
                    if prev_val > 0:
                        r = (values[i] - prev_val - net_cf) / prev_val
                        daily_returns.append(r)
                daily_returns = np.array(daily_returns) if daily_returns else np.array([])

                # Sharpe Ratio (annualized, rf=0)
                if len(daily_returns) >= 5:
                    mean_return = np.mean(daily_returns)
                    std_return = np.std(daily_returns, ddof=1)
                    if std_return > 0:
                        sharpe = (mean_return / std_return) * np.sqrt(252)
                        sharpe_color = "#28a745" if sharpe >= 0 else "#dc3545"
                        sharpe_str = html.Span(
                            f"{sharpe:.2f}",
                            style={"color": sharpe_color},
                        )

                # Max Drawdown
                running_max = np.maximum.accumulate(values)
                drawdowns = (values - running_max) / running_max * 100
                max_dd = np.min(drawdowns)
                max_drawdown_str = html.Span(
                    f"{max_dd:.2f}%",
                    style={"color": "#dc3545" if max_dd < -5 else "#ffc107" if max_dd < 0 else "#28a745"},
                )

    # Cash Allocation %
    if total_value > 0:
        cash_pct = (total_cash_balance / total_value) * 100
        cash_pct_str = f"{cash_pct:.1f}%"
    else:
        cash_pct_str = "N/A"
    cash_amount_str = f"€{total_cash_balance:,.2f}"

    # ========== CHARTS ==========

    # Chart 1: Portfolio vs Benchmark (Return Index)
    returns_fig = _create_empty_figure("Insufficient price history")

    if position_tickers and data_coverage >= 2:
        price_history = get_price_history(position_tickers)

        all_dates = set()
        for ticker_data in price_history.values():
            for point in ticker_data:
                all_dates.add(point["date"])

        if all_dates:
            sorted_dates = sorted(all_dates)
            portfolio_values = []

            for day in sorted_dates:
                day_value = total_cash_balance
                for ticker, shares in ticker_shares.items():
                    ticker_prices = {pt["date"]: pt["close"] for pt in price_history.get(ticker, [])}
                    if day in ticker_prices:
                        day_value += shares * ticker_prices[day]
                    elif ticker_prices:
                        available = [p_day for p_day in ticker_prices.keys() if p_day <= day]
                        if available:
                            day_value += shares * ticker_prices[max(available)]

                portfolio_values.append(day_value)

            if len(portfolio_values) >= 2 and portfolio_values[0] > 0:
                # Normalize to 100
                base_value = portfolio_values[0]
                indexed_values = [(v / base_value) * 100 for v in portfolio_values]

                returns_fig = go.Figure()
                returns_fig.add_trace(go.Scatter(
                    x=sorted_dates,
                    y=indexed_values,
                    mode="lines",
                    name="Portfolio",
                    line=dict(color="#2D7DFF", width=2),
                ))

                returns_fig.update_layout(
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=1.02,
                        xanchor="right",
                        x=1,
                        font=dict(color="rgba(255,255,255,0.8)"),
                    ),
                    yaxis_title="Index (100 = start)",
                )
                _apply_chart_theme(returns_fig)

    # Chart 2: Drawdown
    drawdown_fig = _create_empty_figure("Insufficient price history")

    if position_tickers and data_coverage >= 2:
        price_history = get_price_history(position_tickers)

        all_dates = set()
        for ticker_data in price_history.values():
            for point in ticker_data:
                all_dates.add(point["date"])

        if all_dates:
            sorted_dates = sorted(all_dates)
            portfolio_values = []

            for day in sorted_dates:
                day_value = total_cash_balance
                for ticker, shares in ticker_shares.items():
                    ticker_prices = {pt["date"]: pt["close"] for pt in price_history.get(ticker, [])}
                    if day in ticker_prices:
                        day_value += shares * ticker_prices[day]
                    elif ticker_prices:
                        available = [p_day for p_day in ticker_prices.keys() if p_day <= day]
                        if available:
                            day_value += shares * ticker_prices[max(available)]

                portfolio_values.append(day_value)

            if len(portfolio_values) >= 2:
                values = np.array(portfolio_values)
                running_max = np.maximum.accumulate(values)
                drawdowns = (values - running_max) / running_max * 100

                drawdown_fig = go.Figure()
                drawdown_fig.add_trace(go.Scatter(
                    x=sorted_dates,
                    y=drawdowns.tolist(),
                    mode="lines",
                    fill="tozeroy",
                    name="Drawdown",
                    line=dict(color="#dc3545", width=1),
                    fillcolor="rgba(220,53,69,0.3)",
                ))
                drawdown_fig.update_layout(yaxis_title="Drawdown %")
                _apply_chart_theme(drawdown_fig)

    # Chart 3: Cash vs Invested (Donut)
    invested_value = market_value_total

    if total_value > 0:
        cash_donut_fig = go.Figure()
        cash_donut_fig.add_trace(go.Pie(
            values=[total_cash_balance, invested_value],
            labels=["Cash", "Invested"],
            hole=0.6,
            marker=dict(colors=["#32C5FF", "#2D7DFF"]),
            textinfo="label+percent",
            textfont=dict(color="white"),
            hovertemplate="<b>%{label}</b><br>€%{value:,.2f}<br>%{percent}<extra></extra>",
        ))
        cash_donut_fig.update_layout(
            showlegend=False,
            annotations=[
                dict(
                    text=f"€{total_value:,.0f}",
                    x=0.5, y=0.5,
                    font=dict(size=18, color="white"),
                    showarrow=False,
                )
            ],
        )
        _apply_chart_theme(cash_donut_fig)
    else:
        cash_donut_fig = _create_empty_figure("No portfolio value")

    # Chart 4: Sector Allocation (Horizontal Bar)
    sector_data = get_all_sector_allocations(position_values)

    if sector_data:
        # Sort by percentage descending
        sector_data.sort(key=lambda x: x["percentage"], reverse=True)

        sectors_fig = go.Figure()
        sectors_fig.add_trace(go.Bar(
            x=[s["percentage"] for s in sector_data],
            y=[s["sector"] for s in sector_data],
            orientation="h",
            marker=dict(color="#2D7DFF"),
            text=[f"{s['percentage']:.1f}%" for s in sector_data],
            textposition="auto",
            textfont=dict(color="white"),
        ))
        sectors_fig.update_layout(
            xaxis_title="Allocation %",
            yaxis=dict(autorange="reversed"),
        )
        _apply_chart_theme(sectors_fig)
    else:
        sectors_fig = _create_empty_figure("No sector data")

    # ========== TOP CONTRIBUTORS TABLE ==========
    contributors_data = []

    for ticker, shares in ticker_shares.items():
        if ticker in latest_prices and ticker in previous_prices:
            curr_price = latest_prices[ticker]
            prev_price = previous_prices[ticker]
            daily_pnl = shares * (curr_price - prev_price)
            daily_pct = ((curr_price - prev_price) / prev_price) * 100 if prev_price > 0 else 0

            contributors_data.append({
                "ticker": ticker,
                "shares": round(shares, 2),
                "prev_price": round(prev_price, 2),
                "curr_price": round(curr_price, 2),
                "daily_pnl": round(daily_pnl, 2),
                "daily_pct": round(daily_pct, 2),
            })

    # Sort by absolute P/L (show all, no top-5 limit)
    contributors_data.sort(key=lambda x: abs(x["daily_pnl"]), reverse=True)

    # Fetch intraday data for sparklines
    today_str = dt_date.today().isoformat()
    intraday_cache = get_intraday_prices(position_tickers, today_str)

    # Try to fetch fresh intraday data for tickers that don't have cached data
    tickers_to_fetch = [t for t in position_tickers if not intraday_cache.get(t)]
    if tickers_to_fetch:
        try:
            # Bulk fetch intraday data from yfinance
            intraday_data = yf.download(tickers_to_fetch, period="1d", interval="5m", group_by="ticker", progress=False)

            for ticker in tickers_to_fetch:
                bars = []
                try:
                    if len(tickers_to_fetch) == 1:
                        ticker_data = intraday_data
                    else:
                        ticker_data = intraday_data[ticker]

                    if not ticker_data.empty:
                        for idx, row in ticker_data.iterrows():
                            if not np.isnan(row.get('Close', np.nan)):
                                bars.append({
                                    "ts": int(idx.timestamp()),
                                    "price": float(row['Close']),
                                })
                except (KeyError, AttributeError):
                    pass

                if bars:
                    upsert_intraday_prices(ticker, today_str, bars)
                    intraday_cache[ticker] = bars
        except Exception:
            pass  # Silently handle yfinance failures

    # Add sparkline to each row
    for row in contributors_data:
        ticker = row["ticker"]
        pos = row["daily_pnl"]
        bars = intraday_cache.get(ticker, [])
        if bars and len(bars) >= 2:
            last_ts = bars[-1]["ts"]
            row["trend"] = f"![t](/sparkline/{ticker}?day={today_str}&pos={pos}&ts={last_ts})"
        else:
            row["trend"] = ""



    return (
        eod_text,
        data_warning,
        total_value_str,
        total_value_change,
        total_return_str,
        benchmark_delta_str,
        benchmark_name_str,
        sharpe_str,
        max_drawdown_str,
        cash_pct_str,
        cash_amount_str,
        returns_fig,
        drawdown_fig,
        cash_donut_fig,
        sectors_fig,
        contributors_data,
    )
