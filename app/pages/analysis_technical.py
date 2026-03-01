from __future__ import annotations

import re
from io import StringIO

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html, MATCH, ALL
from dash.exceptions import PreventUpdate
from plotly.subplots import make_subplots

from app.db.connection import get_connection
from app.db.rebalance_repo import get_ai_settings
from app.db.ledger_repo import list_trades
from app.db.strategy_repo import (
    list_saved_strategies,
    get_saved_strategy,
    upsert_saved_strategy,
    delete_saved_strategy,
    assign_saved_strategy,
)
from app.db.backtest_repo import get_cached_backtest, upsert_cached_backtest
from app.services import technical_service
from app.services.backtest_service import run_backtest
from app.strategy import get_strategies, get_strategy_by_key


def layout() -> html.Div:
    return html.Div(
        children=[
            # Stores
            dcc.Store(id="tech-ohlcv-store", data=None),
            dcc.Store(id="tech-analysis-store", data=None),
            dcc.Store(id="tech-ai-payload", data=None),
            dcc.Store(id="tech-active-tab", data="overview"),
            dcc.Store(id="tech-bt-params", data={}),
            dcc.Store(id="tech-bt-strategy", data=None),
            dcc.Store(id="tech-bt-job", data=None),
            dcc.Store(id="tech-bt-result", data=None),
            # Polling interval for backtest jobs
            dcc.Interval(id="tech-bt-poll", interval=800, n_intervals=0, disabled=True),
            # Page header
            html.Div(
                className="page-header",
                children=[
                    html.Div(
                        children=[
                            html.H2("Analysis – Technical", style={"margin": "0"}),
                            html.Div(
                                "Chart-based technical analysis with automated pattern recognition.",
                                className="page-subtitle",
                            ),
                        ]
                    ),
                    html.Div(
                        className="page-header-actions",
                        children=[
                            html.Div(
                                [
                                    html.Div("Ticker", className="field-label"),
                                    dcc.Input(
                                        id="tech-ticker-input",
                                        type="text",
                                        placeholder="Enter ticker (e.g., AAPL)",
                                        debounce=True,
                                        style={"minWidth": "140px"},
                                    ),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Div("Period", className="field-label"),
                                    dcc.Dropdown(
                                        id="tech-period",
                                        className="dd-solid-dark",
                                        options=[
                                            {"label": "3 Months", "value": "3mo"},
                                            {"label": "6 Months", "value": "6mo"},
                                            {"label": "1 Year", "value": "1y"},
                                            {"label": "2 Years", "value": "2y"},
                                            {"label": "5 Years", "value": "5y"},
                                            {"label": "TTM", "value": "TTM"},
                                        ],
                                        value="1y",
                                        clearable=False,
                                        style={"minWidth": "140px"},
                                    ),
                                ]
                            ),
                            html.Div(
                                [
                                    html.Div(style={"height": "20px"}),  # Spacer
                                    html.Button(
                                        "Analyze",
                                        id="tech-analyze-btn",
                                        className="btn-primary",
                                    ),
                                ]
                            ),
                        ],
                    ),
                ],
            ),
            # Status bar
            html.Div(
                id="tech-status-bar",
                className="status-bar",
                children="Enter a ticker and click Analyze to load charts.",
            ),
            # Nav pills
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    dbc.Nav(
                        pills=True,
                        className="segmented-pills",
                        children=[
                            dbc.NavLink("Overview", id="tech-tab-overview", active=True),
                            dbc.NavLink("Patterns", id="tech-tab-patterns", disabled=True),
                            dbc.NavLink("Backtest", id="tech-tab-backtest"),
                        ],
                    ),
                ],
            ),
            # Content panels
            html.Div(id="tech-overview-content", style={"display": "block"}),
            html.Div(id="tech-backtest-content", style={"display": "none"}),
        ],
    )


def get_position_context(ticker: str, portfolio_id: int = 1) -> dict:
    """Get position context including total P/L % for risk management analysis.

    Returns dict with:
        - has_position: bool
        - avg_entry_price: float
        - current_shares: float
        - unrealized_pl_pct: float (current P/L based on current position)
        - unrealized_pl_eur: float
        - total_pl_pct: float (lifetime P/L including realized + unrealized with commissions)
        - total_pl_eur: float
    """
    conn = get_connection()
    try:
        # Get all transactions for this ticker
        transactions = conn.execute(
            """
            SELECT transaction_type, shares, price, commission
            FROM transactions
            WHERE portfolio_id = ? AND ticker = ?
            ORDER BY transaction_date
            """,
            (portfolio_id, ticker)
        ).fetchall()

        if not transactions:
            return {
                "has_position": False,
                "avg_entry_price": 0.0,
                "current_shares": 0.0,
                "unrealized_pl_pct": 0.0,
                "unrealized_pl_eur": 0.0,
                "total_pl_pct": 0.0,
                "total_pl_eur": 0.0,
            }

        # Calculate current position and cost basis
        current_shares = 0.0
        total_cost_with_comm = 0.0
        total_proceeds_with_comm = 0.0

        for txn in transactions:
            txn_type = txn["transaction_type"]
            shares = txn["shares"]
            price = txn["price"]
            commission = txn["commission"] or 0.0

            if txn_type == "buy":
                current_shares += shares
                total_cost_with_comm += (shares * price) + commission
            elif txn_type == "sell":
                current_shares -= shares
                total_proceeds_with_comm += (shares * price) - commission

        has_position = current_shares > 0.01

        # Calculate average entry price (cost basis / shares for current position)
        avg_entry_price = 0.0
        if has_position and current_shares > 0:
            # Use FIFO to calculate avg cost of remaining shares
            remaining = current_shares
            cost_basis = 0.0
            for txn in transactions:
                if txn["transaction_type"] == "buy" and remaining > 0:
                    take_shares = min(remaining, txn["shares"])
                    cost_basis += take_shares * txn["price"]
                    remaining -= take_shares
            avg_entry_price = cost_basis / current_shares if current_shares > 0 else 0.0

        # Get current price from latest transaction (or could fetch from yfinance)
        current_price = transactions[-1]["price"] if transactions else 0.0

        # Unrealized P/L (current position only)
        unrealized_pl_eur = 0.0
        unrealized_pl_pct = 0.0
        if has_position:
            current_value = current_shares * current_price
            cost_basis_current = current_shares * avg_entry_price
            if cost_basis_current > 0:
                unrealized_pl_eur = current_value - cost_basis_current
                unrealized_pl_pct = (unrealized_pl_eur / cost_basis_current) * 100

        # Total P/L % (lifetime including realized + unrealized with commissions)
        total_pl_eur = 0.0
        total_pl_pct = 0.0

        if total_cost_with_comm > 0:
            current_value = current_shares * current_price if has_position else 0.0
            # Total P/L = (proceeds from sells + current value) - total cost
            total_pl_eur = (total_proceeds_with_comm + current_value) - total_cost_with_comm
            total_pl_pct = (total_pl_eur / total_cost_with_comm) * 100

        return {
            "has_position": has_position,
            "avg_entry_price": avg_entry_price,
            "current_shares": current_shares,
            "unrealized_pl_pct": unrealized_pl_pct,
            "unrealized_pl_eur": unrealized_pl_eur,
            "total_pl_pct": total_pl_pct,
            "total_pl_eur": total_pl_eur,
        }
    finally:
        conn.close()


@callback(
    Output("tech-ohlcv-store", "data"),
    Output("tech-analysis-store", "data"),
    Output("tech-ai-payload", "data"),
    Output("tech-status-bar", "children"),
    Input("tech-analyze-btn", "n_clicks"),
    State("tech-ticker-input", "value"),
    State("tech-period", "value"),
    prevent_initial_call=True,
)
def fetch_and_analyze(n_clicks, ticker_input, period):
    # Validate ticker
    if not ticker_input or not ticker_input.strip():
        return None, None, None, "Please enter a ticker symbol"

    ticker = ticker_input.strip().upper()
    if not re.match(r"^[A-Z0-9.\-]+$", ticker):
        return None, None, None, "Invalid ticker format"

    # Map TTM to 1y
    period_actual = "1y" if period == "TTM" else period

    # Fetch OHLCV data
    df, error = technical_service.get_ohlcv_data(ticker, period_actual)
    if error:
        return None, None, None, error

    # Analyze signal
    signal = technical_service.analyze_technical_signal(df)

    # Prepare AI payload
    latest = df.iloc[-1]
    ai_payload = {
        "ticker": ticker,
        "signal_type": signal["signal_type"],
        "signal_name": signal["signal_name"],
        "setup_quality_score": signal["setup_quality_score"],
        "trend_direction": signal["trend_direction"],
        "rsi": signal["rsi"],
        "adx": signal["adx"],
        "atr_pct": signal["atr_pct"],
        "volatility_level": signal["volatility_level"],
        "momentum": signal["momentum"],
        "reasons": signal["reasons"],
        "last_close": float(latest["Close"]),
        "daily_change": float(latest.get("Daily_Change", 0)),
        "macd": float(latest.get("MACD", 0)),
        "macd_signal": float(latest.get("MACD_Signal", 0)),
        "bb_position": "Above Upper"
        if latest["Close"] > latest["BB_Upper"]
        else "Below Lower"
        if latest["Close"] < latest["BB_Lower"]
        else "Middle",
    }

    # Add position context for risk management analysis
    position_context = get_position_context(ticker, portfolio_id=1)
    ai_payload["position_context"] = position_context

    # Serialize DataFrame to JSON
    ohlcv_json = df.to_json(orient="split")

    # Status message
    last_date = df.index[-1].strftime("%Y-%m-%d")
    status = f"Analysis complete | {ticker} | Period: {period} | Last candle: {last_date}"

    return ohlcv_json, signal, ai_payload, status


@callback(
    Output("tech-overview-content", "children"),
    Input("tech-analysis-store", "data"),
    State("tech-ohlcv-store", "data"),
)
def render_overview(analysis_data, ohlcv_data):
    if not analysis_data:
        return html.Div(
            "Click Analyze to load technical analysis.", className="hint-text"
        )

    # Deserialize DataFrame
    df = pd.read_json(StringIO(ohlcv_data), orient="split")

    # Build KPI cards (2 rows × 3 cols)
    kpi_cards = [
        # Card 1: Signal
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div(
                    "Signal",
                    className="hint-text",
                    style={"marginBottom": "5px"},
                ),
                html.Div(
                    analysis_data["signal_type"],
                    style={
                        "fontSize": "20px",
                        "fontWeight": "600",
                        "color": "var(--ok)"
                        if analysis_data["signal_type"] == "GO"
                        else "var(--warning)"
                        if analysis_data["signal_type"] == "CAUTION"
                        else "var(--danger)",
                    },
                ),
                html.Div(
                    analysis_data["signal_name"],
                    style={"fontSize": "12px", "marginTop": "4px"},
                ),
            ],
        ),
        # Card 2: Setup Quality
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div(
                    "Setup Quality",
                    className="hint-text",
                    style={"marginBottom": "5px"},
                ),
                html.Div(
                    f"{analysis_data['setup_quality_score']}/100",
                    style={"fontSize": "24px", "fontWeight": "600"},
                ),
            ],
        ),
        # Card 3: Volatility
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div(
                    "Volatility",
                    className="hint-text",
                    style={"marginBottom": "5px"},
                ),
                html.Div(
                    analysis_data["volatility_level"],
                    style={"fontSize": "20px", "fontWeight": "600"},
                ),
                html.Div(
                    f"ATR {analysis_data['atr_pct']:.2f}%",
                    style={"fontSize": "12px", "marginTop": "4px"},
                ),
            ],
        ),
        # Card 4: Trend
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div(
                    "Trend", className="hint-text", style={"marginBottom": "5px"}
                ),
                html.Div(
                    analysis_data["trend_direction"],
                    style={
                        "fontSize": "20px",
                        "fontWeight": "600",
                        "color": "var(--ok)"
                        if analysis_data["trend_direction"] == "Bullish"
                        else "var(--danger)"
                        if analysis_data["trend_direction"] == "Bearish"
                        else "var(--text)",
                    },
                ),
            ],
        ),
        # Card 5: Momentum
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div(
                    "Momentum", className="hint-text", style={"marginBottom": "5px"}
                ),
                html.Div(
                    analysis_data["momentum"],
                    style={"fontSize": "18px", "fontWeight": "600"},
                ),
            ],
        ),
        # Card 6: RSI + ADX
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div(
                    "Indicators",
                    className="hint-text",
                    style={"marginBottom": "5px"},
                ),
                html.Div(
                    f"RSI {analysis_data['rsi']:.1f}",
                    style={"fontSize": "16px", "fontWeight": "600"},
                ),
                html.Div(
                    f"ADX {analysis_data['adx']:.1f}",
                    style={
                        "fontSize": "16px",
                        "fontWeight": "600",
                        "marginTop": "4px",
                    },
                ),
            ],
        ),
    ]

    # Build setup reasons card
    reasons_card = html.Div(
        className="card",
        children=[
            html.Div("Setup Analysis", className="card-title"),
            html.Ul([html.Li(reason) for reason in analysis_data["reasons"]]),
        ],
    )

    # Build chart (5 subplots)
    fig = build_chart_figure(df)
    chart_card = html.Div(
        className="card",
        children=[
            html.Div("Charts & Indicators", className="card-title"),
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
        ],
    )

    # AI card with loading
    ai_card = html.Div(
        className="card",
        children=[
            html.Div("AI Technical Analysis", className="card-title"),
            dcc.Loading(
                type="dot",
                children=html.Div(id="tech-ai-output"),
            ),
        ],
    )

    return html.Div(
        [
            html.Div(kpi_cards[:3], className="grid-3", style={"marginBottom": "14px"}),
            html.Div(kpi_cards[3:], className="grid-3", style={"marginBottom": "14px"}),
            html.Div(reasons_card, style={"marginBottom": "14px"}),
            html.Div(chart_card, style={"marginBottom": "14px"}),
            html.Div(ai_card),
        ]
    )


def build_chart_figure(df: pd.DataFrame) -> go.Figure:
    """Build 5-subplot technical analysis chart."""
    fig = make_subplots(
        rows=5,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.4, 0.15, 0.15, 0.15, 0.15],
        subplot_titles=("Price & Moving Averages", "Volume", "RSI", "MACD", "ADX"),
    )

    # Subplot 1: Candlestick + Bollinger Bands + SMAs
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1,
        col=1,
    )

    # Bollinger Bands
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["BB_Upper"],
            line=dict(color="rgba(250, 128, 114, 0.5)", width=1),
            name="BB Upper",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["BB_Lower"],
            line=dict(color="rgba(250, 128, 114, 0.5)", width=1),
            name="BB Lower",
            fill="tonexty",
            fillcolor="rgba(250, 128, 114, 0.1)",
        ),
        row=1,
        col=1,
    )

    # EMAs
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA_20"],
            line=dict(color="#2196F3", width=1),
            name="EMA 20",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["EMA_50"],
            line=dict(color="#FF9800", width=1),
            name="EMA 50",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["SMA_200"],
            line=dict(color="#9C27B0", width=1),
            name="SMA 200",
        ),
        row=1,
        col=1,
    )

    # Subplot 2: Volume
    colors = [
        "#26a69a" if close > open_ else "#ef5350"
        for close, open_ in zip(df["Close"], df["Open"])
    ]
    fig.add_trace(
        go.Bar(x=df.index, y=df["Volume"], marker_color=colors, name="Volume"),
        row=2,
        col=1,
    )

    # Subplot 3: RSI
    fig.add_trace(
        go.Scatter(x=df.index, y=df["RSI"], line=dict(color="#2196F3"), name="RSI"),
        row=3,
        col=1,
    )
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=3, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=3, col=1)

    # Subplot 4: MACD
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["MACD"], line=dict(color="#2196F3"), name="MACD"
        ),
        row=4,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["MACD_Signal"],
            line=dict(color="#FF9800"),
            name="Signal",
        ),
        row=4,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=df.index, y=df["MACD_Hist"], marker_color="#B0BEC5", name="Histogram"),
        row=4,
        col=1,
    )

    # Subplot 5: ADX
    fig.add_trace(
        go.Scatter(x=df.index, y=df["ADX"], line=dict(color="#9C27B0"), name="ADX"),
        row=5,
        col=1,
    )
    fig.add_hline(y=25, line_dash="dash", line_color="orange", row=5, col=1)

    # Dark theme styling
    fig.update_layout(
        template="plotly_dark",
        height=900,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e0e0e0"),
        margin=dict(l=50, r=50, t=50, b=50),
    )

    fig.update_xaxes(
        gridcolor="#2a2a2a",
        showgrid=True,
        rangeslider_visible=False,
    )
    fig.update_yaxes(gridcolor="#2a2a2a", showgrid=True)

    return fig


@callback(
    Output("tech-ai-output", "children"),
    Input("tech-ai-payload", "data"),
)
def generate_ai_analysis(payload):
    if not payload:
        raise PreventUpdate

    try:
        ai_settings = get_ai_settings(portfolio_id=1)
        if not ai_settings or not ai_settings.get("enabled"):
            return html.Div("Local AI analysis unavailable.", className="hint-text")

        # Build prompt
        reasons_bullets = "\n".join([f"- {r}" for r in payload["reasons"]])
        prompt = f"""
You are a senior, portfolio-aware technical analyst.

IMPORTANT ROLE DEFINITION
- Your role is to EXPLAIN the current technical situation in the context of an
  EXISTING systematic strategy signal and portfolio risk management.
- You must NOT generate independent buy/sell recommendations.
- You must NOT override or contradict the system signal or stop-loss logic.
- If indicators conflict, explain the conflict clearly instead of forcing a conclusion.

Assume the user may already be in a position.

------------------------------------------------
ASSET & SYSTEM CONTEXT
------------------------------------------------
Ticker: {payload['ticker']}
System Signal: {payload['signal_type']} ({payload['signal_name']})
Setup Quality Score: {payload['setup_quality_score']}/100

------------------------------------------------
TECHNICAL STATE (EOD, DAILY)
------------------------------------------------
Trend Structure (EMA20 vs EMA50): {payload['trend_direction']}
RSI(14): {payload['rsi']:.1f}
ADX(14): {payload['adx']:.1f}
ATR%: {payload['atr_pct']:.2f}%
MACD Momentum: {"Positive" if payload['macd'] > payload['macd_signal'] else "Negative"}
Bollinger Band Position: {payload['bb_position']}
Volatility Regime (relative): {payload['volatility_level']}

Recent Price Action:
- Last Close: ${payload['last_close']:.2f}
- Daily Change: {payload['daily_change']:+.2f}%

System Rationale:
{reasons_bullets}

------------------------------------------------
POSITION CONTEXT (FOR EXPLANATION ONLY)
------------------------------------------------
This position context is provided for RISK EXPLANATION ONLY.
It must NOT be used to override strategy signals or stops.

Current Position: {"Yes" if payload.get("position_context", {}).get("has_position") else "No"}
Average Entry Price: ${payload.get("position_context", {}).get("avg_entry_price", 0):.2f}
Current Shares: {payload.get("position_context", {}).get("current_shares", 0):.2f}

Current Position P/L:
- Unrealized P/L: {payload.get("position_context", {}).get("unrealized_pl_pct", 0):+.2f}%
- Unrealized P/L (EUR): €{payload.get("position_context", {}).get("unrealized_pl_eur", 0):+.0f}

Lifetime Total P/L (includes all realized + unrealized + commissions):
- Total P/L: {payload.get("position_context", {}).get("total_pl_pct", 0):+.2f}%
- Total P/L (EUR): €{payload.get("position_context", {}).get("total_pl_eur", 0):+.0f}

------------------------------------------------
ANALYSIS INSTRUCTIONS
------------------------------------------------
Explain the situation using a PROFESSIONAL, RISK-FIRST mindset.

Address ALL of the following explicitly:

1. **Market Regime Assessment**
   - Use ADX as the PRIMARY regime indicator.
   - Clearly state whether this is:
     - Trend-following dominant (ADX > 25)
     - Transitional (ADX 20–25)
     - Mean-reversion dominant (ADX < 20)
   - If ADX is transitional, explicitly warn that both trend-following and
     mean-reversion signals are lower quality.

2. **Indicator Alignment & Conflict**
   - Explain what RSI, MACD, and trend structure each indicate.
   - If indicators conflict, describe WHY this typically happens in this regime.
   - Do NOT reinterpret conflicts as new trade signals.

3. **Interpretation of the System Signal**
   - Explain why the system-generated signal (BUY / SELL / HOLD / CAUTION)
     is reasonable given the regime and indicator state.
   - If short-term bounces are possible, explain why they do NOT invalidate
     risk reduction or exits when momentum or structure weakens.

4. **Risk Management Perspective (Critical)**
   - Clearly distinguish:
       - Strategy exits (indicator/thesis-based)
       - Stop-loss exits (price-based, unconditional)
   - Explicitly state that stops must NEVER be delayed or ignored due to indicators.
   - If unrealized losses are present, explain risk asymmetry WITHOUT justifying
     averaging down or overriding exits.

5. **What Would Change the Picture**
   - Describe the MINIMUM technical conditions required BEFORE a new BUY or
     re-entry would be justified.
   - Focus on structure, trend strength, and momentum confirmation
     (not single-indicator triggers).

------------------------------------------------
STRICT CONSTRAINTS
------------------------------------------------
- Do NOT suggest new trades or entries unless the System Signal is BUY.
- Do NOT issue standalone BUY or SELL commands.
- Do NOT use emotional or predictive language.
- Do NOT weaken stop-loss discipline.

------------------------------------------------
OUTPUT FORMAT
------------------------------------------------
Provide a structured explanation with these sections:

- **Regime Summary**
- **Indicator Interpretation**
- **Why the Current Signal Is Reasonable**
- **Risk Management Perspective**
- **What to Watch Next**

Tone:
- Calm
- Objective
- Portfolio-manager level
- No hype, no certainty

Length:
~300–400 words.

Language: english

Base your reasoning STRICTLY on the data above and choose your words so new traders like me can understand it. Also clearly mention the trend by name.
"""



        # Call AI
        import requests

        base_url = ai_settings.get("base_url", "http://localhost:11434")
        model = ai_settings.get("model", "llama3.1:8b")
        timeout_ms = ai_settings.get("timeout_ms", 30000)

        response = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout_ms / 1000,
        )
        response.raise_for_status()
        ai_text = response.json().get("response", "No response from model.")

        return html.Div(
            dcc.Markdown(ai_text),
            style={"fontSize": "13px", "lineHeight": "1.35"},
        )

    except Exception:
        return html.Div("Local AI analysis unavailable.", className="hint-text")


# ============================================================================
# BACKTEST TAB CALLBACKS
# ============================================================================

@callback(
    Output("tech-active-tab", "data"),
    Output("tech-tab-overview", "active"),
    Output("tech-tab-backtest", "active"),
    Output("tech-overview-content", "style"),
    Output("tech-backtest-content", "style"),
    Input("tech-tab-overview", "n_clicks"),
    Input("tech-tab-backtest", "n_clicks"),
    prevent_initial_call=True,
)
def switch_tabs(overview_clicks, backtest_clicks):
    """Handle tab switching between Overview and Backtest."""
    from dash import ctx

    if not ctx.triggered_id:
        raise PreventUpdate

    if ctx.triggered_id == "tech-tab-backtest":
        return "backtest", False, True, {"display": "none"}, {"display": "block"}
    else:
        return "overview", True, False, {"display": "block"}, {"display": "none"}


@callback(
    Output("tech-backtest-content", "children"),
    Input("tech-active-tab", "data"),
)
def render_backtest_panel(active_tab):
    """Render backtest panel content when tab is active."""
    if active_tab != "backtest":
        raise PreventUpdate

    strategies, _ = get_strategies()
    strategy_options = [{"label": s.name, "value": s.key} for s in strategies]

    return html.Div([
        # Strategy Builder Card
        html.Div(
            className="card",
            style={"marginBottom": "14px"},
            children=[
                html.Div("Strategy Builder", className="card-title"),

                # Strategy Library Accordion (collapsed by default)
                dbc.Accordion(
                    start_collapsed=True,
                    className="mb-3",
                    children=[
                        dbc.AccordionItem(
                            title=html.Div(
                                style={"display": "flex", "alignItems": "center", "gap": "8px"},
                                children=[
                                    html.Span("Strategy Library"),
                                    html.Span(
                                        id="tech-bt-saved-count",
                                        className="badge",
                                        style={
                                            "backgroundColor": "var(--accent)",
                                            "color": "white",
                                            "padding": "2px 8px",
                                            "borderRadius": "4px",
                                            "fontSize": "11px",
                                        },
                                        children="0 saved",
                                    ),
                                ],
                            ),
                            children=[
                                html.Div(
                                    style={
                                        "display": "grid",
                                        "gridTemplateColumns": "2fr 1fr 1fr",
                                        "gap": "12px",
                                        "alignItems": "flex-end",
                                    },
                                    children=[
                                        html.Div(
                                            children=[
                                                html.Div("Saved Strategies", className="field-label"),
                                                dcc.Dropdown(
                                                    id="tech-bt-saved-strategy",
                                                    className="dd-solid-dark",
                                                    options=[],
                                                    value=None,
                                                    placeholder="Select saved...",
                                                    clearable=True,
                                                    style={"minWidth": "140px"},
                                                ),
                                            ],
                                        ),
                                        html.Button("Load", id="tech-bt-load-btn", className="btn-secondary", style={"height": "38px"}),
                                        html.Button("Delete", id="tech-bt-delete-btn", className="btn-secondary", style={"height": "38px"}),
                                    ],
                                ),
                                html.Div(
                                    "Load a saved strategy into the editor.",
                                    className="hint-text",
                                    style={"marginTop": "8px", "fontSize": "12px"},
                                ),
                            ],
                        )
                    ],
                ),

                # Current Strategy Editor
                html.Div(
                    style={"marginBottom": "12px"},
                    children=[
                        html.Div("Base Strategy", className="field-label"),
                        dcc.Dropdown(
                            id="tech-bt-strategy-select",
                            className="dd-solid-dark",
                            options=strategy_options,
                            value="ema_crossover_rsi",  # Default to EMA Crossover + RSI
                            clearable=False,
                            style={"minWidth": "200px", "maxWidth": "400px"},
                        ),
                    ],
                ),

                # Parameter groups container
                html.Div(id="tech-bt-param-container", style={"marginBottom": "16px"}),

                # Save controls at bottom
                html.Div(
                    style={
                        "display": "flex",
                        "gap": "12px",
                        "alignItems": "center",
                        "flexWrap": "wrap",
                    },
                    children=[
                        html.Button("Save Strategy", id="tech-bt-save-btn", className="btn-secondary"),
                        html.Div(
                            id="tech-bt-save-status",
                            className="hint-text",
                            style={"flex": "1"},
                            children="",
                        ),
                        html.Button("Use in Portfolio", id="tech-bt-assign-btn", className="btn-primary"),
                    ],
                ),
            ],
        ),
        # Results Card
        html.Div(
            className="card",
            children=[
                html.Div("Backtest Results", className="card-title"),
                html.Div(
                    style={
                        "display": "flex",
                        "gap": "12px",
                        "alignItems": "flex-end",
                        "marginBottom": "12px",
                    },
                    children=[
                        html.Div(
                            children=[
                                html.Div("Timeframe", className="field-label"),
                                dcc.Dropdown(
                                    id="tech-bt-timeframe",
                                    className="dd-solid-dark",
                                    options=[
                                        {"label": "3 Months", "value": "3mo"},
                                        {"label": "6 Months", "value": "6mo"},
                                        {"label": "1 Year", "value": "1y"},
                                        {"label": "2 Years", "value": "2y"},
                                        {"label": "5 Years", "value": "5y"},
                                    ],
                                    value="1y",
                                    clearable=False,
                                    style={"minWidth": "140px"},
                                ),
                            ],
                        ),
                        html.Button(
                            "Run Backtest",
                            id="tech-bt-run-btn",
                            className="btn-primary",
                            style={"height": "38px"},
                        ),
                    ],
                ),
                html.Div(
                    id="tech-bt-run-status",
                    className="hint-text",
                    style={"marginBottom": "16px", "minHeight": "18px"},
                    children="",
                ),
                # Results container (updated by callback)
                html.Div(id="tech-bt-results-container"),
            ],
        ),
    ])


def _bt_kpi_card(label: str, value: str) -> html.Div:
    """Helper for backtest KPI card."""
    return html.Div(
        style={
            "padding": "12px",
            "backgroundColor": "var(--surface-2)",
            "borderRadius": "8px",
            "textAlign": "center",
        },
        children=[
            html.Div(label, className="hint-text", style={"fontSize": "11px", "marginBottom": "4px"}),
            html.Div(value, style={"fontSize": "18px", "fontWeight": "600"}),
        ],
    )


def _empty_bt_chart() -> go.Figure:
    """Empty placeholder for backtest equity curve."""
    fig = go.Figure()
    fig.update_layout(
        template="plotly_dark",
        height=300,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text="Run a backtest to see equity curve.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=14, color="#888"),
            )
        ],
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig


@callback(
    Output("tech-bt-params", "data"),
    Output("tech-bt-param-container", "children"),
    Input("tech-bt-strategy-select", "value"),
    State("tech-bt-params", "data"),
    prevent_initial_call=False,
)
def load_strategy_params(strategy_key, current_params):
    """Load strategy and render parameter controls with sliders."""
    if not strategy_key:
        raise PreventUpdate

    strategy_def = get_strategy_by_key(strategy_key)
    if not strategy_def:
        return {}, html.Div("Strategy not found.", className="hint-text")

    # Use current params if available (from load operation), otherwise defaults
    # Check if current_params matches this strategy (has same keys)
    if current_params and set(current_params.keys()) == set(strategy_def.default_params.keys()):
        params_data = current_params.copy()
    else:
        params_data = strategy_def.default_params.copy()

    # Group parameters
    groups = {"main": [], "filters": [], "stops": []}
    for spec in strategy_def.param_specs:
        groups[spec.group].append(spec)

    # Render groups
    group_elements = []
    for group_name in ["main", "filters", "stops"]:
        specs = groups[group_name]
        if not specs:
            continue

        group_title = {
            "main": "Main Parameters",
            "filters": "Filters",
            "stops": "Stop Loss & Take Profit",
        }[group_name]

        inputs = [_render_param_control(spec, params_data[spec.id]) for spec in specs]

        group_elements.append(
            html.Div(
                style={
                    "padding": "14px",
                    "backgroundColor": "var(--surface-1)",
                    "borderRadius": "8px",
                },
                children=[
                    html.Div(
                        group_title,
                        style={"fontWeight": "600", "marginBottom": "14px", "fontSize": "14px"},
                    ),
                    html.Div(inputs),
                ],
            )
        )

    return params_data, html.Div(
        style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "14px"},
        children=group_elements,
    )


def _render_param_control(spec, current_value):
    """Render parameter control - use sliders for numeric params."""
    from dash import MATCH

    param_id = {"type": "tech-bt-param", "param": spec.id}

    if spec.ptype == "bool":
        return html.Div(
            style={"marginBottom": "14px"},
            children=[
                dbc.Checkbox(
                    id=param_id,
                    label=spec.label,
                    value=current_value,
                ),
            ],
        )
    elif spec.ptype in ["int", "float"]:
        # Use slider for numeric params
        marks = None
        if spec.min_val is not None and spec.max_val is not None:
            # Create marks at key points
            range_size = spec.max_val - spec.min_val
            if range_size <= 20:
                # Show all marks for small ranges
                marks = {int(i): str(int(i)) for i in range(int(spec.min_val), int(spec.max_val) + 1, max(1, int(range_size / 10)))}
            else:
                # Show fewer marks for large ranges
                step_size = range_size / 5
                marks = {int(spec.min_val + i * step_size): f"{spec.min_val + i * step_size:.0f}" for i in range(6)}

        return html.Div(
            style={"marginBottom": "18px"},
            children=[
                html.Div(
                    style={"display": "flex", "justifyContent": "space-between", "marginBottom": "4px"},
                    children=[
                        html.Div(spec.label, className="field-label"),
                        html.Div(
                            id={"type": "tech-bt-param-label", "param": spec.id},
                            style={"fontWeight": "600", "fontSize": "12px", "color": "var(--accent)"},
                            children=str(current_value),
                        ),
                    ],
                ),
                dcc.Slider(
                    id=param_id,
                    min=spec.min_val,
                    max=spec.max_val,
                    step=spec.step,
                    value=current_value,
                    marks=marks,
                    tooltip={"placement": "bottom", "always_visible": False},
                ),
            ],
        )
    elif spec.ptype == "choice":
        return html.Div(
            style={"marginBottom": "12px"},
            children=[
                html.Div(spec.label, className="field-label"),
                dcc.Dropdown(
                    id=param_id,
                    className="dd-solid-dark",
                    options=[{"label": label, "value": val} for label, val in spec.choices],
                    value=current_value,
                    clearable=False,
                ),
            ],
        )
    else:
        return html.Div(f"Unknown type: {spec.ptype}")


@callback(
    Output("tech-bt-params", "data", allow_duplicate=True),
    Input({"type": "tech-bt-param", "param": ALL}, "value"),
    State({"type": "tech-bt-param", "param": ALL}, "id"),
    State("tech-bt-params", "data"),
    prevent_initial_call=True,
)
def update_params_store(values, ids, current_params):
    """Update params store when any parameter changes."""
    if not ids or not values:
        raise PreventUpdate

    updated_params = current_params.copy() if current_params else {}
    for param_id, value in zip(ids, values):
        if value is not None:
            param_name = param_id["param"]
            updated_params[param_name] = value

    return updated_params


@callback(
    Output({"type": "tech-bt-param-label", "param": MATCH}, "children"),
    Input({"type": "tech-bt-param", "param": MATCH}, "value"),
    prevent_initial_call=True,
)
def update_param_label(value):
    """Update parameter label display."""
    if value is None:
        raise PreventUpdate

    # Format label based on type
    if isinstance(value, float):
        return f"{value:.2f}"
    else:
        return str(value)


# ============================================================================
# PHASE 3: STRATEGY SAVE/LOAD/DELETE/ASSIGN CALLBACKS
# ============================================================================

@callback(
    Output("tech-bt-saved-strategy", "options"),
    Output("tech-bt-saved-count", "children"),
    Input("tech-active-tab", "data"),
    Input("tech-bt-save-btn", "n_clicks"),
    Input("tech-bt-delete-btn", "n_clicks"),
    State("tech-ticker-input", "value"),
)
def load_saved_strategies_list(active_tab, save_clicks, delete_clicks, ticker):
    """Populate saved strategies dropdown and update count badge based on active ticker."""
    if active_tab != "backtest" or not ticker:
        return [], "0 saved"

    portfolio_id = 1  # Hardcoded for Phase 3
    strategies = list_saved_strategies(portfolio_id, ticker)

    options = [{"label": s["name"], "value": s["id"]} for s in strategies]
    count = len(strategies)
    count_text = f"{count} saved" if count != 1 else "1 saved"

    return options, count_text


@callback(
    Output("tech-bt-save-status", "children"),
    Output("tech-bt-saved-strategy", "value"),
    Input("tech-bt-save-btn", "n_clicks"),
    Input("tech-bt-load-btn", "n_clicks"),
    Input("tech-bt-delete-btn", "n_clicks"),
    Input("tech-bt-assign-btn", "n_clicks"),
    State("tech-bt-strategy-select", "value"),
    State("tech-bt-params", "data"),
    State("tech-bt-saved-strategy", "value"),
    State("tech-ticker-input", "value"),
    prevent_initial_call=True,
)
def handle_strategy_actions(
    save_clicks,
    load_clicks,
    delete_clicks,
    assign_clicks,
    base_strategy_key,
    params,
    selected_saved_id,
    ticker,
):
    """Handle save/load/delete/assign actions in a single callback."""
    from dash import ctx
    from datetime import datetime

    if not ctx.triggered_id:
        raise PreventUpdate

    portfolio_id = 1  # Hardcoded for Phase 3
    triggered = ctx.triggered_id

    if not ticker or not ticker.strip():
        return "Error: No ticker selected", None

    ticker = ticker.strip().upper()

    # SAVE
    if triggered == "tech-bt-save-btn":
        if not base_strategy_key:
            return "Error: Select a base strategy", None
        if not params:
            return "Error: No parameters to save", None

        # Auto-generate strategy name: <ticker>-<base_strategy>-<timestamp dd/mm/yyyy hh:mm>
        timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        strategy_name = f"{ticker}-{base_strategy_key}-{timestamp}"

        try:
            saved_id = upsert_saved_strategy(
                portfolio_id=portfolio_id,
                ticker=ticker,
                name=strategy_name,
                base_strategy_key=base_strategy_key,
                params=params,
                notes=None,
            )
            return f"✓ Saved '{strategy_name}'", saved_id
        except Exception as e:
            return f"Error saving: {str(e)}", None

    # LOAD
    elif triggered == "tech-bt-load-btn":
        if not selected_saved_id:
            return "Error: Select a saved strategy first", None

        # Load will be handled by separate callback to avoid circular dependencies
        return "Loading...", selected_saved_id

    # DELETE
    elif triggered == "tech-bt-delete-btn":
        if not selected_saved_id:
            return "Error: Select a saved strategy to delete", None

        try:
            delete_saved_strategy(portfolio_id, ticker, selected_saved_id)
            timestamp = datetime.now().strftime("%H:%M:%S")
            return f"✓ Deleted at {timestamp}", None
        except Exception as e:
            return f"Error deleting: {str(e)}", None

    # ASSIGN
    elif triggered == "tech-bt-assign-btn":
        if not selected_saved_id:
            return "Error: Select a saved strategy to assign", None

        try:
            assign_saved_strategy(portfolio_id, ticker, selected_saved_id)
            timestamp = datetime.now().strftime("%H:%M:%S")
            return f"✓ Assigned to {ticker} at {timestamp}", selected_saved_id
        except Exception as e:
            return f"Error assigning: {str(e)}", None

    return "", None


@callback(
    Output("tech-bt-strategy-select", "value"),
    Output("tech-bt-params", "data", allow_duplicate=True),
    Input("tech-bt-load-btn", "n_clicks"),
    State("tech-bt-saved-strategy", "value"),
    State("tech-ticker-input", "value"),
    prevent_initial_call=True,
)
def load_saved_strategy(load_clicks, selected_saved_id, ticker):
    """Load a saved strategy and restore base strategy + params."""
    if not selected_saved_id or not ticker:
        raise PreventUpdate

    portfolio_id = 1  # Hardcoded for Phase 3
    strategy = get_saved_strategy(portfolio_id, ticker, selected_saved_id)

    if not strategy:
        raise PreventUpdate

    # Return base strategy key and params
    # The load_strategy_params callback will handle re-rendering the param UI
    return strategy["base_strategy_key"], strategy["params"]


# ============================================================================
# PHASE 4: BACKTEST ENGINE EXECUTION
# ============================================================================

# Module-level job tracker and thread pool
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

_backtest_jobs = {}  # {job_id: {status, result, error}}
_executor = ThreadPoolExecutor(max_workers=1)


def _run_backtest_async(job_id: str, ticker: str, strategy_key: str, params: dict, timeframe: str, portfolio_id: int):
    """Run backtest in background thread."""
    try:
        # Check cache first
        cached = get_cached_backtest(portfolio_id, ticker, strategy_key, params, timeframe)
        if cached:
            _backtest_jobs[job_id] = {
                "status": "complete",
                "result": cached,
                "cached": True,
                "error": None,
            }
            return

        # Run backtest
        result = run_backtest(ticker, strategy_key, params, timeframe)

        # Cache result
        upsert_cached_backtest(portfolio_id, ticker, strategy_key, params, timeframe, result)

        _backtest_jobs[job_id] = {
            "status": "complete",
            "result": result,
            "cached": False,
            "error": None,
        }
    except Exception as e:
        _backtest_jobs[job_id] = {
            "status": "error",
            "result": None,
            "cached": False,
            "error": str(e),
        }


@callback(
    Output("tech-bt-job", "data"),
    Output("tech-bt-poll", "disabled"),
    Output("tech-bt-run-status", "children"),
    Input("tech-bt-run-btn", "n_clicks"),
    State("tech-ticker-input", "value"),
    State("tech-bt-strategy-select", "value"),
    State("tech-bt-params", "data"),
    State("tech-bt-timeframe", "value"),
    prevent_initial_call=True,
)
def run_backtest_job(n_clicks, ticker, strategy_key, params, timeframe):
    """Start backtest job in background thread."""
    if not ticker or not ticker.strip():
        return None, True, "Error: Enter a ticker symbol"

    if not strategy_key:
        return None, True, "Error: Select a base strategy"

    if not params:
        return None, True, "Error: No parameters configured"

    ticker = ticker.strip().upper()
    portfolio_id = 1

    # Create job
    job_id = str(uuid.uuid4())
    _backtest_jobs[job_id] = {"status": "running", "result": None, "cached": False, "error": None}

    # Submit to thread pool
    _executor.submit(_run_backtest_async, job_id, ticker, strategy_key, params, timeframe, portfolio_id)

    # Return job metadata and enable polling
    job_data = {
        "job_id": job_id,
        "ticker": ticker,
        "strategy_key": strategy_key,
        "timeframe": timeframe,
    }

    return job_data, False, "Running backtest..."


@callback(
    Output("tech-bt-result", "data"),
    Output("tech-bt-poll", "disabled", allow_duplicate=True),
    Output("tech-bt-run-status", "children", allow_duplicate=True),
    Input("tech-bt-poll", "n_intervals"),
    State("tech-bt-job", "data"),
    prevent_initial_call=True,
)
def poll_backtest_job(n_intervals, job_data):
    """Poll backtest job status and update results when complete."""
    if not job_data or "job_id" not in job_data:
        return None, True, ""

    job_id = job_data["job_id"]
    job = _backtest_jobs.get(job_id)

    if not job:
        return None, True, "Error: Job not found"

    if job["status"] == "running":
        # Still running, keep polling
        raise PreventUpdate

    elif job["status"] == "complete":
        # Complete, return result and disable polling
        result = job["result"]
        exec_time = result.get("execution_time_ms", 0)
        cached_str = " (cached)" if job.get("cached") else ""
        status = f"✓ Complete in {exec_time:.0f}ms{cached_str}"

        # Clean up job
        del _backtest_jobs[job_id]

        return result, True, status

    elif job["status"] == "error":
        # Error occurred
        error_msg = job.get("error", "Unknown error")
        status = f"Error: {error_msg}"

        # Clean up job
        del _backtest_jobs[job_id]

        return None, True, status

    return None, True, ""


@callback(
    Output("tech-bt-results-container", "children"),
    Input("tech-bt-result", "data"),
)
def render_backtest_results(result):
    """Render backtest results: KPIs + equity chart."""
    if not result:
        # Show placeholders
        return [
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(6, 1fr)",
                    "gap": "12px",
                    "marginBottom": "20px",
                },
                children=[
                    _bt_kpi_card("Total Return", "—"),
                    _bt_kpi_card("Max Drawdown", "—"),
                    _bt_kpi_card("Sharpe Ratio", "—"),
                    _bt_kpi_card("Win Rate", "—"),
                    _bt_kpi_card("# Trades", "—"),
                    _bt_kpi_card("Avg Trade", "—"),
                ],
            ),
            dcc.Graph(
                figure=_empty_bt_chart(),
                config={"displayModeBar": False},
            ),
        ]

    # Extract stats and equity series
    stats = result.get("stats", {})
    equity_series = result.get("equity_series", [])

    # Build KPI cards with real values
    kpi_cards = [
        _bt_kpi_card("Total Return", f"{stats.get('total_return', 0):+.1f}%"),
        _bt_kpi_card("Max Drawdown", f"{stats.get('max_drawdown', 0):.1f}%"),
        _bt_kpi_card("Sharpe Ratio", f"{stats.get('sharpe_ratio', 0):.2f}"),
        _bt_kpi_card("Win Rate", f"{stats.get('win_rate', 0):.0f}%"),
        _bt_kpi_card("# Trades", str(stats.get('num_trades', 0))),
        _bt_kpi_card("Avg Trade", f"{stats.get('avg_trade', 0):+.2f}%"),
    ]

    # Build equity curve chart
    if equity_series:
        dates = [item[0] for item in equity_series]
        equity = [item[1] for item in equity_series]

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=dates,
                y=equity,
                mode="lines",
                line=dict(color="#2196F3", width=2),
                name="Equity",
                fill="tozeroy",
                fillcolor="rgba(33, 150, 243, 0.1)",
            )
        )

        fig.update_layout(
            template="plotly_dark",
            height=300,
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(title="Date", gridcolor="#2a2a2a"),
            yaxis=dict(title="Equity", gridcolor="#2a2a2a"),
            margin=dict(l=50, r=50, t=20, b=50),
        )

        chart = dcc.Graph(figure=fig, config={"displayModeBar": False})
    else:
        chart = dcc.Graph(figure=_empty_bt_chart(), config={"displayModeBar": False})

    return [
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(6, 1fr)",
                "gap": "12px",
                "marginBottom": "20px",
            },
            children=kpi_cards,
        ),
        chart,
    ]
