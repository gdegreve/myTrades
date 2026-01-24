from __future__ import annotations

from dash import html, dcc, Input, Output, callback
from dash.dash_table import DataTable

from app.db.repo_portfolio import list_portfolios, list_holdings


def layout() -> html.Div:
    return html.Div(
        children=[
            html.H2("Portfolio – Manage"),
            html.P("Read-only list from SQLite. Select a portfolio to load holdings."),
            html.Div(id="manage-portfolios-status", style={"margin": "8px 0"}),

            DataTable(
                id="manage-portfolios-table",
                columns=[
                    {"name": "ID", "id": "id"},
                    {"name": "Name", "id": "name"},
                ],
                data=[],
                page_size=15,
                row_selectable="single",
                selected_rows=[],
                style_table={"overflowX": "auto"},
                style_cell={"padding": "6px", "textAlign": "left"},
                style_header={"fontWeight": "600"},
            ),

            html.Hr(style={"margin": "16px 0"}),

            html.H3("Holdings"),
            html.Div(id="manage-holdings-status", style={"margin": "8px 0"}),

            DataTable(
                id="manage-holdings-table",
                columns=[
                    {"name": "Ticker", "id": "ticker"},
                    {"name": "Shares", "id": "total_shares"},
                    {"name": "Avg Cost", "id": "avg_cost"},
                    {"name": "Sector", "id": "sector"},
                    {"name": "Last Updated", "id": "last_updated"},
                ],
                data=[],
                page_size=20,
                style_table={"overflowX": "auto"},
                style_cell={"padding": "6px", "textAlign": "left"},
                style_header={"fontWeight": "600"},
            ),
        ]
    )


@callback(
    Output("manage-portfolios-table", "data"),
    Output("manage-portfolios-status", "children"),
    Input("url", "pathname"),
)
def load_manage_portfolios(pathname: str):
    if pathname != "/portfolio/manage":
        return [], ""

    try:
        rows = list_portfolios()
    except Exception as exc:
        return [], html.Div(f"DB error: {exc}", style={"color": "crimson"})

    if not rows:
        return [], html.Div(
            "No portfolios found (or table 'portfolios' does not exist yet).",
            style={"color": "#555"},
        )

    return rows, html.Div(f"Loaded {len(rows)} portfolio(s). Select one to view holdings.", style={"color": "#555"})


@callback(
    Output("manage-holdings-table", "data"),
    Output("manage-holdings-status", "children"),
    Input("url", "pathname"),
    Input("manage-portfolios-table", "selected_rows"),
    Input("manage-portfolios-table", "data"),
)
def load_holdings_for_selected(pathname: str, selected_rows: list[int], portfolios_data: list[dict]):
    if pathname != "/portfolio/manage":
        return [], ""

    if not portfolios_data:
        return [], ""

    if not selected_rows:
        return [], html.Div("Select a portfolio above to load holdings.", style={"color": "#555"})

    row_index = selected_rows[0]
    if row_index < 0 or row_index >= len(portfolios_data):
        return [], html.Div("Invalid selection.", style={"color": "crimson"})

    portfolio_id = portfolios_data[row_index]["id"]
    portfolio_name = portfolios_data[row_index].get("name", "")

    try:
        rows = list_holdings(int(portfolio_id))
    except Exception as exc:
        return [], html.Div(f"DB error: {exc}", style={"color": "crimson"})

    if not rows:
        return [], html.Div(f"No holdings found for '{portfolio_name}'.", style={"color": "#555"})

    return rows, html.Div(f"Loaded {len(rows)} holding(s) for '{portfolio_name}'.", style={"color": "#555"})
