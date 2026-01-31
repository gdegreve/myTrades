import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, html
from flask import request, send_file
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
from datetime import date as dt_date

from app.db.overview_repo import get_intraday_prices
from app.layout import build_layout
from app.db.schema import ensure_schema
from app.pages import (
    portfolio_overview,
    portfolio_manage,
    portfolio_design,
    portfolio_holdings,
    portfolio_signals,
    portfolio_rebalance,
    analysis_fundamental,
    analysis_technical,
    market,
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

# In-memory PNG cache: {(ticker, day, pos, last_ts): PNG bytes}
_sparkline_cache: dict[tuple[str, str, str, int], bytes] = {}


@app.server.route("/sparkline/<ticker>")
def sparkline_png(ticker: str):
    """Serve sparkline PNG for a ticker using intraday data from SQLite."""
    day = request.args.get("day", dt_date.today().isoformat())
    pos = request.args.get("pos", "0")
    last_ts = int(request.args.get("ts", "0"))

    cache_key = (ticker, day, pos, last_ts)

    if cache_key in _sparkline_cache:
        png_bytes = _sparkline_cache[cache_key]
        return send_file(io.BytesIO(png_bytes), mimetype="image/png")

    # Fetch intraday prices from DB
    intraday_data = get_intraday_prices([ticker], day)
    prices = [bar["price"] for bar in intraday_data.get(ticker, [])]

    if not prices or len(prices) < 2:
        # Return 1x1 transparent PNG
        fig, ax = plt.subplots(figsize=(0.1, 0.1))
        ax.axis("off")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", transparent=True)
        plt.close(fig)
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    # Generate sparkline PNG
    is_positive = float(pos) >= 0
    color = "#10b981" if is_positive else "#ef4444"
    fig, ax = plt.subplots(figsize=(1.2, 0.4))
    ax.plot(prices, color=color, linewidth=1.5)
    ax.axis("off")
    ax.margins(0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", pad_inches=0, transparent=True, dpi=80)
    plt.close(fig)
    buf.seek(0)
    png_bytes = buf.read()

    _sparkline_cache[cache_key] = png_bytes
    return send_file(io.BytesIO(png_bytes), mimetype="image/png")


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
    if pathname == "/analysis/fundamental":
        return analysis_fundamental.layout()
    if pathname == "/analysis/technical":
        return analysis_technical.layout()
    if pathname == "/market":
        return market.layout()
    if pathname == "/portfolio/design":
        return portfolio_design.layout()
    if pathname == "/tools/settings":
        return tools_settings.layout()

    return html.Div([html.H2("404"), html.P(f"Unknown path: {pathname}")])


if __name__ == "__main__":
    app.run(debug=True)
