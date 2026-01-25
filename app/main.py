import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, html

from app.layout import build_layout
from app.db.schema import ensure_schema
from app.pages import (
    portfolio_overview,
    portfolio_manage,
    portfolio_design,
    portfolio_holdings,
    portfolio_signals,
    portfolio_rebalance,
    analytics_fundamentals,
    analytics_technical,
    tools_settings,
)

external_stylesheets = [
    "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css",
]

ensure_schema()

app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="MyTrading – Dash",
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css",
    ],
)

app.layout = build_layout()


@app.callback(
    Output("page-content", "children"),
    Input("url", "pathname"),
)
def route(pathname: str):
    if pathname in (None, "/", "/portfolio/overview"):
        return portfolio_overview.layout()
    if pathname == "/portfolio/manage":
        return portfolio_manage.layout()
    if pathname == "/portfolio/holdings":
        return portfolio_holdings.layout()
    if pathname == "/portfolio/signals":
        return portfolio_signals.layout()
    if pathname == "/portfolio/rebalance":
        return portfolio_rebalance.layout() 
    if pathname == "/analytics/fundamentals":
        return analytics_fundamentals.layout()
    if pathname == "/analytics/technical":
        return analytics_technical.layout()
    if pathname == "/portfolio/design":
        return portfolio_design.layout()
    if pathname == "/tools/settings":
        return tools_settings.layout()

    return html.Div([html.H2("404"), html.P(f"Unknown path: {pathname}")])


if __name__ == "__main__":
    app.run(debug=True)
