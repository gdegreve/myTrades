from __future__ import annotations
import dash_bootstrap_components as dbc

from dash import dcc, html, Input, Output, callback, no_update
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate
from datetime import datetime

from app.db.portfolio_repo import list_portfolios
from app.db.ledger_repo import (
    list_trades,
    list_cash_movements,
    get_ticker_sectors,
    get_ticker_regions,
    insert_cash_transaction,
    insert_trade,
)
from app.domain.ledger import (
    compute_cash_balance,
    compute_positions,
    compute_invested_amount,
    check_data_completeness,
    validate_cash_transaction,
    validate_trade,
)
from app.services.market_data import get_latest_daily_closes_cached
from app.db.policy_repo import load_policy_snapshot
import plotly.graph_objects as go


def layout() -> html.Div:
    return html.Div(
        children=[
            # Page header with portfolio selector
            html.Div(
                className="page-header",
                children=[
                    html.Div(
                        children=[
                            html.H2("Portfolio – Holdings (Positions & Cash)", style={"margin": "0"}),
                            html.Div(
                                "View and manage current positions, cash balance, and transaction history.",
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
                                        id="holdings-portfolio",
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

            # Hidden refresh trigger store
            dcc.Store(id="holdings-refresh-trigger", data=0),

            # Status message area
            html.Div(
                id="holdings-status",
                style={"marginBottom": "14px"},
            ),

            # KPI strip: Total Value, Cash, Invested, P&L
            html.Div(
                className="grid-2",
                style={"marginBottom": "14px"},
                children=[
                    # Row 1: Total value + Cash
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Total Value", className="card-title"),
                            html.Div(
                                id="holdings-kpi-total-value",
                                children="€0.00",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div("Cash + market value", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Cash Balance", className="card-title"),
                            html.Div(
                                id="holdings-kpi-cash",
                                children="€0.00",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div("Available for trades", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                ],
            ),

            html.Div(
                className="grid-2",
                style={"marginBottom": "14px"},
                children=[
                    # Row 2: Invested + P&L
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Invested (Cost Basis)", className="card-title"),
                            html.Div(
                                id="holdings-kpi-invested",
                                children="€0.00",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div("Total capital deployed", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Total P&L", className="card-title"),
                            html.Div(
                                id="holdings-kpi-pnl",
                                children="€0.00",
                                style={"fontSize": "24px", "fontWeight": "700", "marginTop": "4px"},
                            ),
                            html.Div("Unrealized gain/loss", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                ],
            ),

            # Nav pills for Positions / Drift
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    dbc.Nav(
                        pills=True,
                        children=[
                            dbc.NavLink(
                                "Current Positions",
                                id="holdings-nav-positions",
                                active=True,
                            ),
                            dbc.NavLink(
                                "Drift",
                                id="holdings-nav-drift",
                                active=False,
                            ),
                        ],
                    ),
                ],
            ),

            # Positions panel (visible by default)
            html.Div(
                id="holdings-panel-positions",
                style={"display": "block"},
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.Div(
                                className="card-title-row",
                                children=[
                                    html.Div("Current Positions", className="card-title"),
                                    html.Div("Computed from transaction ledger", className="hint-text"),
                                ],
                            ),
                            html.Div(
                                id="holdings-data-completeness",
                                style={"marginBottom": "10px"},
                            ),
                            DataTable(
                                id="holdings-positions-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Shares", "id": "shares", "type": "numeric"},
                                    {"name": "Avg Cost (EUR)", "id": "avg_cost", "type": "numeric"},
                                    {"name": "Cost Basis (EUR)", "id": "cost_basis", "type": "numeric"},
                                ],
                                data=[],
                                page_size=10,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),
                ],
            ),

            # Drift panel (hidden by default)
            html.Div(
                id="holdings-panel-drift",
                style={"display": "none"},
                children=[
                    # Drift summary cards
                    html.Div(
                        id="drift-summary-cards",
                        className="grid-3",
                        style={"marginBottom": "14px"},
                    ),

                    # Warning banner
                    html.Div(id="drift-warnings", style={"marginBottom": "14px"}),

                    # Bar charts
                    html.Div(
                        className="grid-2",
                        style={"marginBottom": "14px"},
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Sector Drift", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="drift-sector-chart", config={"displayModeBar": False}),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Region Drift", className="card-title", style={"marginBottom": "10px"}),
                                    dcc.Graph(id="drift-region-chart", config={"displayModeBar": False}),
                                ],
                            ),
                        ],
                    ),

                    # Drift tables
                    html.Div(
                        className="grid-2",
                        children=[
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Sector Drift Details", className="card-title", style={"marginBottom": "10px"}),
                                    DataTable(
                                        id="drift-sector-table",
                                        columns=[
                                            {"name": "Sector", "id": "sector"},
                                            {"name": "Target %", "id": "target_pct", "type": "numeric"},
                                            {"name": "Current %", "id": "current_pct", "type": "numeric"},
                                            {"name": "Drift", "id": "drift_pct", "type": "numeric"},
                                            {"name": "Status", "id": "status"},
                                        ],
                                        data=[],
                                        page_size=10,
                                        style_table={"overflowX": "auto"},
                                        style_cell={"padding": "10px", "textAlign": "left"},
                                        style_header={"fontWeight": "600"},
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card",
                                children=[
                                    html.Div("Region Drift Details", className="card-title", style={"marginBottom": "10px"}),
                                    DataTable(
                                        id="drift-region-table",
                                        columns=[
                                            {"name": "Region", "id": "region"},
                                            {"name": "Target %", "id": "target_pct", "type": "numeric"},
                                            {"name": "Current %", "id": "current_pct", "type": "numeric"},
                                            {"name": "Drift", "id": "drift_pct", "type": "numeric"},
                                            {"name": "Status", "id": "status"},
                                        ],
                                        data=[],
                                        page_size=10,
                                        style_table={"overflowX": "auto"},
                                        style_cell={"padding": "10px", "textAlign": "left"},
                                        style_header={"fontWeight": "600"},
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Cash transactions and Trade ticket sections in accordion
            dbc.Accordion(
                style={"marginTop": "14px"},
                start_collapsed=False,
                children=[
                    # Cash transactions section
                    dbc.AccordionItem(
                        title="Cash Transactions",
                        children=[
                            html.Div(
                                className="grid-3",
                                style={"marginBottom": "14px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Type", className="field-label"),
                                            dbc.Select(
                                                id="cash-type",
                                                options=[
                                                    {"label": "Credit (Deposit)", "value": "credit"},
                                                    {"label": "Debit (Withdrawal)", "value": "debit"},
                                                ],
                                                value="credit",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Amount (EUR)", className="field-label"),
                                            dcc.Input(
                                                id="cash-amount",
                                                type="number",
                                                placeholder="1000.00",
                                                min=0,
                                                step=0.01,
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Date", className="field-label"),
                                            dbc.Input(
                                                id="cash-date",
                                                type="date",
                                                value="2026-01-24",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                            html.Div(
                                className="grid-2",
                                style={"marginBottom": "14px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Note", className="field-label"),
                                            dcc.Input(
                                                id="cash-note",
                                                type="text",
                                                placeholder="Optional description",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        style={"display": "flex", "alignItems": "flex-end"},
                                        children=[
                                            html.Button(
                                                "Add cash transaction",
                                                id="cash-add-btn",
                                                className="btn-primary",
                                                n_clicks=0,
                                                style={"width": "100%"},
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card-title-row",
                                style={"marginTop": "18px"},
                                children=[
                                    html.Div("Recent Cash Transactions", className="card-title"),
                                    html.Div("Last 10 entries", className="hint-text"),
                                ],
                            ),
                            DataTable(
                                id="holdings-cash-table",
                                columns=[
                                    {"name": "Date", "id": "date"},
                                    {"name": "Type", "id": "type"},
                                    {"name": "Amount (EUR)", "id": "amount", "type": "numeric"},
                                    {"name": "Note", "id": "note"},
                                ],
                                data=[],
                                page_size=10,
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),
                    # Trade ticket section
                    dbc.AccordionItem(
                        title="Trade Ticket",
                        children=[
                            html.Div(
                                className="grid-3",
                                style={"marginBottom": "14px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Action", className="field-label"),
                                            dbc.Select(
                                                id="trade-action",
                                                options=[
                                                    {"label": "Buy", "value": "buy"},
                                                    {"label": "Sell", "value": "sell"},
                                                ],
                                                value="buy",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Ticker", className="field-label"),
                                            dcc.Input(
                                                id="trade-ticker",
                                                type="text",
                                                placeholder="AAPL",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Quantity", className="field-label"),
                                            dcc.Input(
                                                id="trade-qty",
                                                type="number",
                                                placeholder="10",
                                                min=0,
                                                step=0.01,
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                            html.Div(
                                className="grid-3",
                                style={"marginBottom": "14px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Price (EUR)", className="field-label"),
                                            dcc.Input(
                                                id="trade-price",
                                                type="number",
                                                placeholder="175.50",
                                                min=0,
                                                step=0.01,
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Commission (EUR)", className="field-label"),
                                            dcc.Input(
                                                id="trade-commission",
                                                type="number",
                                                placeholder="0.00",
                                                min=0,
                                                step=0.01,
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Date", className="field-label"),
                                            dbc.Input(
                                                id="trade-date",
                                                type="date",
                                                value="2026-01-24",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                            html.Div(
                                className="grid-2",
                                style={"marginBottom": "14px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Note", className="field-label"),
                                            dcc.Input(
                                                id="trade-note",
                                                type="text",
                                                placeholder="Optional description",
                                                className="text-input",
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        style={"display": "flex", "alignItems": "flex-end"},
                                        children=[
                                            html.Button(
                                                "Execute trade",
                                                id="trade-execute-btn",
                                                className="btn-primary",
                                                n_clicks=0,
                                                style={"width": "100%"},
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card-title-row",
                                style={"marginTop": "18px"},
                                children=[
                                    html.Div("Recent Trades", className="card-title"),
                                    html.Div("Last 10 transactions", className="hint-text"),
                                ],
                            ),
                            DataTable(
                                id="holdings-trades-table",
                                columns=[
                                    {"name": "Date", "id": "date"},
                                    {"name": "Action", "id": "action"},
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Qty", "id": "qty", "type": "numeric"},
                                    {"name": "Price (EUR)", "id": "price", "type": "numeric"},
                                    {"name": "Commission", "id": "commission", "type": "numeric"},
                                    {"name": "Note", "id": "note"},
                                ],
                                data=[],
                                page_size=10,
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


def _compute_drift_analysis(portfolio_id, positions, prices, cash_balance, ticker_sectors, ticker_regions, policy_snapshot):
    """Compute drift analysis comparing current allocations to policy targets.

    Returns dict with sector_drift, region_drift, cash_drift, and warnings.
    """
    # Calculate total portfolio value
    market_value_total = 0.0
    position_values = {}

    for p in positions:
        ticker = p["ticker"]
        if ticker in prices:
            market_value = p["shares"] * prices[ticker]
            market_value_total += market_value
            position_values[ticker] = market_value

    total_value = cash_balance + market_value_total

    if total_value == 0:
        return {
            "sector_drift": [],
            "region_drift": [],
            "cash_drift": None,
            "warnings": ["Portfolio value is zero"],
        }

    warnings = []

    # Compute sector allocations
    sector_allocations = {}
    unclassified_value = 0.0

    for ticker, value in position_values.items():
        sector = ticker_sectors.get(ticker, "")
        if sector:
            sector_allocations[sector] = sector_allocations.get(sector, 0.0) + value
        else:
            unclassified_value += value
            warnings.append(f"{ticker} missing sector classification")

    if unclassified_value > 0:
        sector_allocations["Unclassified"] = unclassified_value

    # Compute region allocations
    region_allocations = {}
    unclassified_region_value = 0.0

    if ticker_regions:
        for ticker, value in position_values.items():
            region = ticker_regions.get(ticker, "")
            if region:
                region_allocations[region] = region_allocations.get(region, 0.0) + value
            else:
                unclassified_region_value += value

        if unclassified_region_value > 0:
            region_allocations["Unclassified"] = unclassified_region_value
    else:
        warnings.append("Region data not available (ticker_regions table missing)")

    # Build sector drift table
    sector_targets = {t["sector"]: t for t in policy_snapshot.get("sector_targets", [])}
    sector_drift = []

    for sector, value in sector_allocations.items():
        current_pct = (value / total_value) * 100
        target_info = sector_targets.get(sector, {})
        target_pct = target_info.get("target_pct", 0.0) or 0.0
        min_pct = target_info.get("min_pct", 0.0) or 0.0
        max_pct = target_info.get("max_pct", 0.0) or 0.0

        drift_pct = current_pct - target_pct

        # Status logic
        if sector == "Unclassified":
            status = "BREACH" if current_pct > 0 else "OK"
        elif current_pct < min_pct or current_pct > max_pct:
            status = "BREACH"
        elif abs(current_pct - min_pct) < 0.5 or abs(current_pct - max_pct) < 0.5:
            status = "WARN"
        else:
            status = "OK"

        sector_drift.append({
            "sector": sector,
            "target_pct": target_pct,
            "current_pct": current_pct,
            "drift_pct": drift_pct,
            "status": status,
        })

    # Add sectors with targets but no current holdings
    for sector, target_info in sector_targets.items():
        if sector not in sector_allocations:
            target_pct = target_info.get("target_pct", 0.0) or 0.0
            min_pct = target_info.get("min_pct", 0.0) or 0.0

            status = "BREACH" if target_pct > 0 or min_pct > 0 else "OK"

            sector_drift.append({
                "sector": sector,
                "target_pct": target_pct,
                "current_pct": 0.0,
                "drift_pct": -target_pct,
                "status": status,
            })

    sector_drift.sort(key=lambda x: abs(x["drift_pct"]), reverse=True)

    # Build region drift table
    region_targets = {t["region"]: t for t in policy_snapshot.get("region_targets", [])}
    region_drift = []

    if ticker_regions:
        for region, value in region_allocations.items():
            current_pct = (value / total_value) * 100
            target_info = region_targets.get(region, {})
            target_pct = target_info.get("target_pct", 0.0) or 0.0
            min_pct = target_info.get("min_pct", 0.0) or 0.0
            max_pct = target_info.get("max_pct", 0.0) or 0.0

            drift_pct = current_pct - target_pct

            # Status logic
            if region == "Unclassified":
                status = "BREACH" if current_pct > 0 else "OK"
            elif current_pct < min_pct or current_pct > max_pct:
                status = "BREACH"
            elif abs(current_pct - min_pct) < 0.5 or abs(current_pct - max_pct) < 0.5:
                status = "WARN"
            else:
                status = "OK"

            region_drift.append({
                "region": region,
                "target_pct": target_pct,
                "current_pct": current_pct,
                "drift_pct": drift_pct,
                "status": status,
            })

        # Add regions with targets but no current holdings
        for region, target_info in region_targets.items():
            if region not in region_allocations:
                target_pct = target_info.get("target_pct", 0.0) or 0.0
                min_pct = target_info.get("min_pct", 0.0) or 0.0

                status = "BREACH" if target_pct > 0 or min_pct > 0 else "OK"

                region_drift.append({
                    "region": region,
                    "target_pct": target_pct,
                    "current_pct": 0.0,
                    "drift_pct": -target_pct,
                    "status": status,
                })

        region_drift.sort(key=lambda x: abs(x["drift_pct"]), reverse=True)

    # Compute cash drift
    cash_pct = (cash_balance / total_value) * 100
    policy = policy_snapshot.get("policy", {})
    cash_target = policy.get("cash_target_pct", 0.0) or 0.0
    cash_min = policy.get("cash_min_pct", 0.0) or 0.0
    cash_max = policy.get("cash_max_pct", 0.0) or 0.0

    cash_drift_pct = cash_pct - cash_target

    if cash_pct < cash_min or cash_pct > cash_max:
        cash_status = "BREACH"
    elif abs(cash_pct - cash_min) < 0.5 or abs(cash_pct - cash_max) < 0.5:
        cash_status = "WARN"
    else:
        cash_status = "OK"

    cash_drift = {
        "target_pct": cash_target,
        "current_pct": cash_pct,
        "drift_pct": cash_drift_pct,
        "status": cash_status,
    }

    return {
        "sector_drift": sector_drift,
        "region_drift": region_drift,
        "cash_drift": cash_drift,
        "warnings": warnings,
    }


@callback(
    Output("holdings-portfolio", "options"),
    Output("holdings-portfolio", "value"),
    Input("url", "pathname"),
)
def populate_portfolio_dropdown(pathname):
    """Populate portfolio dropdown on page load."""
    if pathname != "/portfolio/holdings":
        raise PreventUpdate
    portfolios = list_portfolios()
    if not portfolios:
        return [], None
    options = [{"label": p["name"], "value": p["id"]} for p in portfolios]
    return options, portfolios[0]["id"]


# Pill styling constants (aligned with sidebar brand green)
PILL_ACTIVE_STYLE = {
    "backgroundColor": "#0ea5a5",
    "color": "white",
    "border": "1px solid #0ea5a5",
}

PILL_INACTIVE_STYLE = {
    "backgroundColor": "white",
    "color": "#0ea5a5",
    "border": "1px solid #0ea5a5",
}


@callback(
    Output("holdings-panel-positions", "style"),
    Output("holdings-panel-drift", "style"),
    Output("holdings-nav-positions", "active"),
    Output("holdings-nav-drift", "active"),
    Output("holdings-nav-positions", "style"),
    Output("holdings-nav-drift", "style"),
    Input("holdings-nav-positions", "n_clicks"),
    Input("holdings-nav-drift", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_holdings_panels(positions_clicks, drift_clicks):
    """Toggle between Positions and Drift panels based on pill clicks."""
    from dash import ctx

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "holdings-nav-positions":
        # Show positions panel, hide drift
        return (
            {"display": "block"},  # positions panel
            {"display": "none"},   # drift panel
            True,                  # positions active
            False,                 # drift active
            PILL_ACTIVE_STYLE,     # positions style
            PILL_INACTIVE_STYLE,   # drift style
        )
    elif button_id == "holdings-nav-drift":
        # Hide positions panel, show drift
        return (
            {"display": "none"},   # positions panel
            {"display": "block"},  # drift panel
            False,                 # positions active
            True,                  # drift active
            PILL_INACTIVE_STYLE,   # positions style
            PILL_ACTIVE_STYLE,     # drift style
        )

    raise PreventUpdate


@callback(
    Output("holdings-positions-table", "data"),
    Output("holdings-cash-table", "data"),
    Output("holdings-trades-table", "data"),
    Output("holdings-kpi-cash", "children"),
    Output("holdings-kpi-invested", "children"),
    Output("holdings-kpi-total-value", "children"),
    Output("holdings-kpi-pnl", "children"),
    Output("holdings-data-completeness", "children"),
    Output("drift-summary-cards", "children"),
    Output("drift-sector-chart", "figure"),
    Output("drift-region-chart", "figure"),
    Output("drift-sector-table", "data"),
    Output("drift-region-table", "data"),
    Output("drift-warnings", "children"),
    Input("holdings-portfolio", "value"),
    Input("holdings-refresh-trigger", "data"),
)
def refresh_holdings_data(portfolio_id, refresh_trigger):
    """Refresh all holdings data when portfolio changes.

    Uses ledger-based computation: reads transactions and cash_transactions,
    then computes positions and cash balance in Python (no materialized views).
    """
    if portfolio_id is None:
        raise PreventUpdate

    # Fetch ledger data from DB (read-only)
    trades = list_trades(portfolio_id, limit=1000)  # Increase limit for full computation
    cash_movements = list_cash_movements(portfolio_id, limit=1000)
    ticker_sectors = get_ticker_sectors(portfolio_id)
    ticker_regions = get_ticker_regions(portfolio_id)

    # Compute derived state using domain logic
    positions = compute_positions(trades)
    cash_balance = compute_cash_balance(cash_movements, trades)
    invested_amount = compute_invested_amount(positions)
    completeness = check_data_completeness(positions, ticker_sectors)

    # Fetch latest daily close prices for all position tickers
    position_tickers = [p["ticker"] for p in positions]
    prices, missing_tickers = get_latest_daily_closes_cached(
        position_tickers,
        max_age_minutes=60,
        force_refresh=False,
    )

    # Compute market values and unrealized P&L
    market_value_total = 0.0
    for p in positions:
        ticker = p["ticker"]
        if ticker in prices:
            market_value = p["shares"] * prices[ticker]
            market_value_total += market_value

    # Total portfolio value = cash + market value of holdings
    total_value = cash_balance + market_value_total

    # Total P&L = market value - invested amount (unrealized)
    total_pnl = market_value_total - invested_amount

    # Transform positions for display
    positions_data = [
        {
            "ticker": p["ticker"],
            "shares": round(p["shares"], 4),
            "avg_cost": round(p["avg_cost"], 2),
            "cost_basis": round(p["cost_basis"], 2),
        }
        for p in positions
    ]

    # Transform cash transactions for display (most recent first)
    cash_data = [
        {
            "date": c["transaction_date"],
            "type": c["cash_type"].capitalize(),
            "amount": round(c["amount_eur"], 2),
            "note": c["notes"],
        }
        for c in reversed(cash_movements[-10:])  # Last 10, reversed for display
    ]

    # Transform trades for display (most recent first)
    trades_data = [
        {
            "date": t["transaction_date"],
            "action": t["transaction_type"].capitalize(),
            "ticker": t["ticker"],
            "qty": round(t["shares"], 4),
            "price": round(t["price_eur"], 2) if t["price_eur"] else 0.0,
            "commission": round(t["commission"], 2),
            "note": t["notes"],
        }
        for t in reversed(trades[-10:])  # Last 10, reversed for display
    ]

    # Format KPIs
    cash_str = f"€{cash_balance:,.2f}"
    invested_str = f"€{invested_amount:,.2f}"

    # Format Total Value and P&L with partial indicator if prices missing
    if missing_tickers:
        partial_suffix = f" (partial: {len(missing_tickers)} missing)"
        total_value_str = f"€{total_value:,.2f}{partial_suffix}"
        pnl_str = f"€{total_pnl:,.2f}{partial_suffix}"
    else:
        total_value_str = f"€{total_value:,.2f}"
        pnl_str = f"€{total_pnl:,.2f}"

    # Data completeness indicator
    completeness_msg = ""
    warnings = []

    if completeness["missing_sectors"] > 0:
        tickers = ", ".join(completeness["missing_sectors_tickers"])
        warnings.append(f"{completeness['missing_sectors']} ticker(s) missing sector: {tickers}")

    if missing_tickers:
        missing_str = ", ".join(missing_tickers)
        warnings.append(f"{len(missing_tickers)} ticker(s) missing prices: {missing_str}")

    if warnings:
        completeness_msg = html.Div(
            " | ".join(warnings),
            style={"color": "#856404", "backgroundColor": "#fff3cd", "padding": "6px 10px", "borderRadius": "4px", "fontSize": "13px"},
        )

    # Compute drift analysis
    policy_snapshot = load_policy_snapshot(portfolio_id)
    has_policy = bool(policy_snapshot.get("policy")) or bool(policy_snapshot.get("sector_targets"))

    if has_policy:
        drift_analysis = _compute_drift_analysis(
            portfolio_id, positions, prices, cash_balance, ticker_sectors, ticker_regions, policy_snapshot
        )

        # Build summary cards
        sector_breaches = sum(1 for s in drift_analysis["sector_drift"] if s["status"] == "BREACH")
        region_breaches = sum(1 for r in drift_analysis["region_drift"] if r["status"] == "BREACH")
        cash_drift_info = drift_analysis["cash_drift"]

        summary_cards = [
            html.Div(
                className="card",
                children=[
                    html.Div("Sector Breaches", className="card-title"),
                    html.Div(
                        str(sector_breaches),
                        style={"fontSize": "28px", "fontWeight": "700", "marginTop": "4px", "color": "#dc3545" if sector_breaches > 0 else "#28a745"},
                    ),
                ],
            ),
            html.Div(
                className="card",
                children=[
                    html.Div("Region Breaches", className="card-title"),
                    html.Div(
                        str(region_breaches) if ticker_regions else "N/A",
                        style={"fontSize": "28px", "fontWeight": "700", "marginTop": "4px", "color": "#dc3545" if region_breaches > 0 else "#28a745"},
                    ),
                ],
            ),
            html.Div(
                className="card",
                children=[
                    html.Div("Cash vs Target", className="card-title"),
                    html.Div(
                        f"{cash_drift_info['current_pct']:.1f}% vs {cash_drift_info['target_pct']:.1f}%",
                        style={"fontSize": "18px", "fontWeight": "700", "marginTop": "4px"},
                    ),
                    dbc.Badge(
                        cash_drift_info['status'],
                        color="success" if cash_drift_info['status'] == "OK" else ("warning" if cash_drift_info['status'] == "WARN" else "danger"),
                        style={"marginTop": "6px"},
                    ),
                ],
            ),
        ]

        # Build sector drift chart
        sector_chart_data = drift_analysis["sector_drift"][:10]  # Top 10 by drift magnitude
        sector_fig = go.Figure()
        sector_fig.add_trace(go.Bar(
            x=[s["drift_pct"] for s in sector_chart_data],
            y=[s["sector"] for s in sector_chart_data],
            orientation='h',
            marker=dict(
                color=["#dc3545" if s["drift_pct"] > 0 else "#007bff" for s in sector_chart_data]
            ),
        ))
        sector_fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            height=300,
            xaxis_title="Drift (%)",
            yaxis=dict(autorange="reversed"),
            showlegend=False,
            plot_bgcolor="white",
            paper_bgcolor="white",
        )

        # Build region drift chart
        if ticker_regions and drift_analysis["region_drift"]:
            region_chart_data = drift_analysis["region_drift"][:10]
            region_fig = go.Figure()
            region_fig.add_trace(go.Bar(
                x=[r["drift_pct"] for r in region_chart_data],
                y=[r["region"] for r in region_chart_data],
                orientation='h',
                marker=dict(
                    color=["#dc3545" if r["drift_pct"] > 0 else "#007bff" for r in region_chart_data]
                ),
            ))
            region_fig.update_layout(
                margin=dict(l=0, r=0, t=0, b=0),
                height=300,
                xaxis_title="Drift (%)",
                yaxis=dict(autorange="reversed"),
                showlegend=False,
                plot_bgcolor="white",
                paper_bgcolor="white",
            )
        else:
            region_fig = go.Figure()
            region_fig.add_annotation(
                text="No region data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14, color="#6c757d"),
            )
            region_fig.update_layout(
                margin=dict(l=0, r=0, t=0, b=0),
                height=300,
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                plot_bgcolor="white",
                paper_bgcolor="white",
            )

        # Build drift tables
        sector_table_data = [
            {
                "sector": s["sector"],
                "target_pct": f"{s['target_pct']:.1f}",
                "current_pct": f"{s['current_pct']:.1f}",
                "drift_pct": f"{s['drift_pct']:+.1f}",
                "status": s["status"],
            }
            for s in drift_analysis["sector_drift"]
        ]

        region_table_data = [
            {
                "region": r["region"],
                "target_pct": f"{r['target_pct']:.1f}",
                "current_pct": f"{r['current_pct']:.1f}",
                "drift_pct": f"{r['drift_pct']:+.1f}",
                "status": r["status"],
            }
            for r in drift_analysis["region_drift"]
        ] if ticker_regions else []

        # Warnings banner
        drift_warnings_msg = ""
        if drift_analysis["warnings"]:
            drift_warnings_msg = html.Div(
                " | ".join(drift_analysis["warnings"]),
                style={"color": "#856404", "backgroundColor": "#fff3cd", "padding": "6px 10px", "borderRadius": "4px", "fontSize": "13px"},
            )

    else:
        # No policy: return empty drift data
        summary_cards = []
        sector_fig = go.Figure()
        region_fig = go.Figure()
        sector_table_data = []
        region_table_data = []
        drift_warnings_msg = ""

    return (
        positions_data,
        cash_data,
        trades_data,
        cash_str,
        invested_str,
        total_value_str,
        pnl_str,
        completeness_msg,
        summary_cards,
        sector_fig,
        region_fig,
        sector_table_data,
        region_table_data,
        drift_warnings_msg,
    )


@callback(
    Output("holdings-status", "children"),
    Output("holdings-refresh-trigger", "data"),
    Output("cash-amount", "value"),
    Output("cash-note", "value"),
    Input("cash-add-btn", "n_clicks"),
    Input("holdings-portfolio", "value"),
    Input("cash-type", "value"),
    Input("cash-amount", "value"),
    Input("cash-date", "value"),
    Input("cash-note", "value"),
    prevent_initial_call=True,
)
def handle_cash_transaction(n_clicks, portfolio_id, cash_type, amount, date, note):
    """Handle cash transaction submission with validation."""
    if not n_clicks or portfolio_id is None:
        raise PreventUpdate

    # Get current state for validation
    trades = list_trades(portfolio_id, limit=1000)
    cash_movements = list_cash_movements(portfolio_id, limit=1000)
    current_balance = compute_cash_balance(cash_movements, trades)

    # Validate inputs
    is_valid, error_msg = validate_cash_transaction(cash_type, amount, current_balance, date)

    if not is_valid:
        error_status = html.Div(
            error_msg,
            style={
                "color": "#721c24",
                "backgroundColor": "#f8d7da",
                "padding": "10px 14px",
                "borderRadius": "4px",
                "fontSize": "14px",
            },
        )
        # Return error message WITHOUT raising PreventUpdate
        # Keep current values unchanged (no_update for refresh trigger and inputs)
        return error_status, no_update, no_update, no_update

    # Insert transaction
    try:
        insert_cash_transaction(
            portfolio_id=portfolio_id,
            cash_type=cash_type,
            amount_eur=amount,
            transaction_date=date,
            notes=note or "",
        )
    except Exception as e:
        error_status = html.Div(
            f"Database error: {str(e)}",
            style={
                "color": "#721c24",
                "backgroundColor": "#f8d7da",
                "padding": "10px 14px",
                "borderRadius": "4px",
                "fontSize": "14px",
            },
        )
        # Return error message without raising PreventUpdate
        return error_status, no_update, no_update, no_update

    # Success status
    action_text = "Deposit" if cash_type == "credit" else "Withdrawal"
    success_status = html.Div(
        f"{action_text} of €{amount:,.2f} saved successfully",
        style={
            "color": "#155724",
            "backgroundColor": "#d4edda",
            "padding": "10px 14px",
            "borderRadius": "4px",
            "fontSize": "14px",
        },
    )

    # Trigger refresh by updating timestamp
    refresh_trigger = datetime.now().timestamp()

    return (
        success_status,
        refresh_trigger,
        None,  # Clear amount input
        "",    # Clear note input
    )


@callback(
    Output("holdings-status", "children", allow_duplicate=True),
    Output("holdings-refresh-trigger", "data", allow_duplicate=True),
    Output("trade-ticker", "value"),
    Output("trade-qty", "value"),
    Output("trade-price", "value"),
    Output("trade-commission", "value"),
    Output("trade-note", "value"),
    Input("trade-execute-btn", "n_clicks"),
    Input("holdings-portfolio", "value"),
    Input("trade-action", "value"),
    Input("trade-ticker", "value"),
    Input("trade-qty", "value"),
    Input("trade-price", "value"),
    Input("trade-commission", "value"),
    Input("trade-date", "value"),
    Input("trade-note", "value"),
    prevent_initial_call=True,
)
def handle_trade_execution(n_clicks, portfolio_id, action, ticker, qty, price, commission, date, note):
    """Handle trade execution with validation."""
    if not n_clicks or portfolio_id is None:
        raise PreventUpdate

    # Get current state for validation
    trades = list_trades(portfolio_id, limit=1000)
    cash_movements = list_cash_movements(portfolio_id, limit=1000)
    positions = compute_positions(trades)
    current_balance = compute_cash_balance(cash_movements, trades)

    # Validate inputs
    is_valid, error_msg = validate_trade(
        transaction_type=action,
        ticker=ticker,
        shares=qty,
        price=price,
        commission=commission,
        current_balance=current_balance,
        current_positions=positions,
        date=date,
    )

    if not is_valid:
        error_status = html.Div(
            error_msg,
            style={
                "color": "#721c24",
                "backgroundColor": "#f8d7da",
                "padding": "10px 14px",
                "borderRadius": "4px",
                "fontSize": "14px",
            },
        )
        # Return error message WITHOUT raising PreventUpdate
        # Keep current values unchanged (no_update for refresh trigger and inputs)
        return error_status, no_update, no_update, no_update, no_update, no_update, no_update

    # Insert trade
    try:
        insert_trade(
            portfolio_id=portfolio_id,
            ticker=ticker,
            transaction_type=action,
            shares=qty,
            price_eur=price,
            commission=commission or 0.0,
            transaction_date=date,
            notes=note or "",
        )
    except Exception as e:
        error_status = html.Div(
            f"Database error: {str(e)}",
            style={
                "color": "#721c24",
                "backgroundColor": "#f8d7da",
                "padding": "10px 14px",
                "borderRadius": "4px",
                "fontSize": "14px",
            },
        )
        # Return error message without raising PreventUpdate
        return error_status, no_update, no_update, no_update, no_update, no_update, no_update

    # Success status
    action_text = action.upper()
    success_status = html.Div(
        f"{action_text} {qty} shares of {ticker.upper()} at €{price:.2f} executed successfully",
        style={
            "color": "#155724",
            "backgroundColor": "#d4edda",
            "padding": "10px 14px",
            "borderRadius": "4px",
            "fontSize": "14px",
        },
    )

    # Trigger refresh by updating timestamp
    refresh_trigger = datetime.now().timestamp()

    return (
        success_status,
        refresh_trigger,
        "",    # Clear ticker
        None,  # Clear qty
        None,  # Clear price
        None,  # Clear commission
        "",    # Clear note
    )
