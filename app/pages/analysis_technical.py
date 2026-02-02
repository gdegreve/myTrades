from __future__ import annotations

import re
from io import StringIO

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html
from dash.exceptions import PreventUpdate
from plotly.subplots import make_subplots

from app.db.rebalance_repo import get_ai_settings
from app.services import technical_service


def layout() -> html.Div:
    return html.Div(
        children=[
            # Stores
            dcc.Store(id="tech-ohlcv-store", data=None),
            dcc.Store(id="tech-analysis-store", data=None),
            dcc.Store(id="tech-ai-payload", data=None),
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
            # Nav pills (Overview only, others disabled)
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    dbc.Nav(
                        pills=True,
                        className="segmented-pills",
                        children=[
                            dbc.NavLink("Overview", active=True),
                            dbc.NavLink("Patterns", disabled=True),
                            dbc.NavLink("Backtest", disabled=True),
                        ],
                    ),
                ],
            ),
            # Overview panel
            html.Div(id="tech-overview-content"),
        ],
        style={"maxWidth": "1400px"},
    )


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
        prompt = f"""Act as a senior technical analyst. Analyze this technical setup:

Ticker: {payload['ticker']}
Signal: {payload['signal_type']} - {payload['signal_name']}
Setup Quality: {payload['setup_quality_score']}/100

Technical Indicators:
- Trend: {payload['trend_direction']} (EMA20 vs EMA50)
- RSI(14): {payload['rsi']:.1f}
- ADX(14): {payload['adx']:.1f}
- ATR%: {payload['atr_pct']:.2f}%
- MACD: {"Bullish" if payload['macd'] > payload['macd_signal'] else "Bearish"}
- Bollinger Position: {payload['bb_position']}
- Volatility: {payload['volatility_level']}

Recent Performance:
- Last Close: ${payload['last_close']:.2f}
- Daily Change: {payload['daily_change']:+.2f}%

Setup Analysis:
{reasons_bullets}

Provide:
1. **Short-Term Outlook** (next 1-2 weeks): Direction and key levels
2. **Trading Strategy**: Entry zones, stop loss, targets (if applicable)
3. **Support/Resistance**: Key levels to watch
4. **Risk Assessment**: What could invalidate this setup
5. **Confidence**: Qualitative assessment (High/Medium/Low) with reasoning

Keep it concise (~350 words), actionable, and based strictly on the technical data above."""

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
