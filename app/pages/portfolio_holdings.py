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
                            html.Div("Requires market prices", className="hint-text", style={"marginTop": "6px"}),
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
                            html.Div("Requires market prices", className="hint-text", style={"marginTop": "6px"}),
                        ],
                    ),
                ],
            ),

            # Positions table
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


@callback(
    Output("holdings-positions-table", "data"),
    Output("holdings-cash-table", "data"),
    Output("holdings-trades-table", "data"),
    Output("holdings-kpi-cash", "children"),
    Output("holdings-kpi-invested", "children"),
    Output("holdings-kpi-total-value", "children"),
    Output("holdings-kpi-pnl", "children"),
    Output("holdings-data-completeness", "children"),
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

    # Compute derived state using domain logic
    positions = compute_positions(trades)
    cash_balance = compute_cash_balance(cash_movements, trades)
    invested_amount = compute_invested_amount(positions)
    completeness = check_data_completeness(positions, ticker_sectors)

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
    total_value_str = "€0.00 (requires prices)"
    pnl_str = "€0.00 (requires prices)"

    # Data completeness indicator
    completeness_msg = ""
    if completeness["missing_sectors"] > 0:
        tickers = ", ".join(completeness["missing_sectors_tickers"])
        completeness_msg = html.Div(
            f"Data: {completeness['missing_sectors']} ticker(s) missing sector: {tickers}",
            style={"color": "#856404", "backgroundColor": "#fff3cd", "padding": "6px 10px", "borderRadius": "4px", "fontSize": "13px"},
        )

    return (
        positions_data,
        cash_data,
        trades_data,
        cash_str,
        invested_str,
        total_value_str,
        pnl_str,
        completeness_msg,
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
