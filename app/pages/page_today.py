"""Today page - Landing dashboard with quick portfolio overview and market status."""
from __future__ import annotations

import json
import time
import requests
from datetime import datetime
from dash import html, dcc, callback, Input, Output, State
from dash.exceptions import PreventUpdate

from app.db.overview_repo import (
    get_active_portfolios_summary,
    get_active_current_positions,
    get_latest_prices,
    get_latest_eod_date,
)
from app.db.rebalance_repo import get_ai_settings
from app.db.policy_repo import load_policy_snapshot
from app.db.ledger_repo import list_trades, list_cash_movements
from app.db.portfolio_repo import get_active_portfolio_ids
from app.db.benchmarks_repo import get_benchmark_eod, ensure_benchmark_eod_cached, list_benchmarks
from app.db.strategy_repo import list_watchlist, get_assignment_map, get_saved_strategy_by_id
from app.domain.ledger import compute_positions, compute_cash_balance
from app.services.signal_service import evaluate_position_signal, evaluate_watchlist_signal
from app.services.market_data import get_latest_daily_closes_cached


def layout() -> html.Div:
    """Render the Today landing page."""
    today = datetime.now().strftime("%A, %B %d, %Y")

    return html.Div(
        className="page",
        children=[
            # Stores for AI brief caching
            dcc.Store(id="ai-brief-cache", data={"text": None, "timestamp": 0, "portfolio_id": None}),
            dcc.Store(id="ai-brief-status", data="idle"),
            dcc.Store(id="ai-brief-collapsed-state", data=True),  # Start collapsed

            html.Div(
                className="page-header",
                children=[
                    html.H1("Today"),
                    html.Div(today, className="text-muted"),
                ],
            ),

            # Welcome Brief Card (AI-powered)
            _welcome_brief_card(),

            # Portfolio Status Cards (2×2 grid)
            html.Div(
                className="grid-2 today-status-grid",
                style={"marginBottom": "20px"},
                children=[
                    html.Div(
                        id="today-markets-card-wrapper",
                        children=[
                            dcc.Link(
                                href="/market",
                                style={"textDecoration": "none"},
                                children=_status_card(
                                    "🌍 Markets",
                                    "today-markets-primary",
                                    "today-markets-sub",
                                ),
                            )
                        ],
                    ),
                    html.Div(
                        id="today-health-card-wrapper",
                        children=[
                            dcc.Link(
                                href="/portfolio/rebalance",
                                style={"textDecoration": "none"},
                                children=_status_card(
                                    "🧠 Portfolio Health",
                                    "today-health-primary",
                                    "today-health-sub",
                                ),
                            )
                        ],
                    ),
                    html.Div(
                        id="today-cash-card-wrapper",
                        children=[
                            dcc.Link(
                                href="/portfolio/rebalance",
                                style={"textDecoration": "none"},
                                children=_status_card(
                                    "💰 Cash & Allocation",
                                    "today-cash-primary",
                                    "today-cash-sub",
                                ),
                            )
                        ],
                    ),
                    html.Div(
                        id="today-signals-card-wrapper",
                        children=[
                            dcc.Link(
                                href="/portfolio/signals",
                                style={"textDecoration": "none"},
                                children=_status_card(
                                    "🚦 Signals & Risk",
                                    "today-signals-primary",
                                    "today-signals-sub",
                                ),
                            )
                        ],
                    ),
                ],
            ),

            # Suggested posture line
            html.Div(
                id="today-posture-line",
                style={"marginBottom": "20px", "fontSize": "14px", "fontWeight": "500"},
                children="→ Suggested posture today: Loading...",
            ),

            html.Div(
                id="today-content",
                className="grid-3",
                children=[
                    _market_status_card(),
                    _portfolio_snapshot_card(),
                    _alerts_card(),
                ],
            ),
        ],
    )


def _market_status_card() -> html.Div:
    """Market status card with last data date."""
    return html.Div(
        className="card",
        children=[
            html.Div("Market Status", className="card-title"),
            html.Div(id="market-status-content", children="Loading..."),
        ],
    )


def _portfolio_snapshot_card() -> html.Div:
    """Portfolio snapshot card with total values."""
    return html.Div(
        className="card",
        children=[
            html.Div("Portfolio Snapshot", className="card-title"),
            html.Div(id="portfolio-snapshot-content", children="Loading..."),
        ],
    )


def _alerts_card() -> html.Div:
    """Alerts and notifications card."""
    return html.Div(
        className="card",
        children=[
            html.Div("Alerts", className="card-title"),
            html.Div(
                className="text-muted",
                children="No alerts at this time",
            ),
        ],
    )


def _welcome_brief_card() -> html.Div:
    """AI-powered Welcome Brief card."""
    return html.Div(
        id="ai-brief-card",
        className="card today-ai-brief ai-brief-collapsed",
        style={"marginBottom": "20px"},
        children=[
            html.Div(
                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                children=[
                    html.Div("Welcome back", className="card-title", style={"marginBottom": "0"}),
                    html.Button(
                        "Expand",
                        id="ai-brief-toggle-btn",
                        className="ai-brief-toggle-btn",
                        n_clicks=0,
                    ),
                ],
            ),
            html.Div(
                className="ai-brief-content-wrapper",
                children=[
                    html.Div(
                        id="ai-brief-content",
                        style={"marginTop": "12px"},
                        children=[
                            html.Div(
                                "Generating today's portfolio brief…",
                                className="today-ai-placeholder",
                                style={"fontStyle": "italic"},
                            ),
                        ],
                    ),
                    html.Div(
                        style={"marginTop": "16px", "display": "flex", "gap": "12px", "alignItems": "center"},
                        children=[
                            html.Button(
                                "Refresh Brief",
                                id="ai-brief-refresh-btn",
                                className="btn-secondary",
                                style={"fontSize": "13px", "padding": "6px 12px"},
                                n_clicks=0,
                            ),
                            html.Div(
                                id="ai-brief-status-text",
                                className="today-ai-status",
                                style={"fontSize": "12px"},
                                children="Status: Idle",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _status_card(title: str, primary_id: str, sub_id: str) -> html.Div:
    """Build a compact status card for Today page."""
    return html.Div(
        className="card",
        children=[
            html.Div(
                title,
                style={"fontSize": "12px", "color": "var(--text-muted)", "marginBottom": "8px", "fontWeight": "600"},
            ),
            html.Div(
                id=primary_id,
                style={"fontSize": "16px", "fontWeight": "600", "color": "white", "marginBottom": "4px"},
                children="Loading...",
            ),
            html.Div(
                id=sub_id,
                style={"fontSize": "12px", "color": "var(--text-muted)"},
                children="",
            ),
        ],
    )


@callback(
    Output("ai-brief-card", "className"),
    Output("ai-brief-toggle-btn", "children"),
    Output("ai-brief-collapsed-state", "data"),
    Input("ai-brief-toggle-btn", "n_clicks"),
    State("ai-brief-collapsed-state", "data"),
    prevent_initial_call=True,
)
def toggle_ai_brief(n_clicks, is_collapsed):
    """Toggle AI brief expand/collapse (manual user action)."""
    if n_clicks is None or n_clicks == 0:
        raise PreventUpdate

    new_state = not is_collapsed
    class_name = "card today-ai-brief ai-brief-collapsed" if new_state else "card today-ai-brief ai-brief-expanded"
    button_text = "Expand" if new_state else "Collapse"

    return class_name, button_text, new_state


@callback(
    Output("market-status-content", "children"),
    Input("today-content", "children"),
)
def load_market_status(_):
    """Load market status data."""
    latest_date = get_latest_eod_date()

    if not latest_date:
        return html.Div("No price data available", className="text-muted")

    return html.Div([
        html.Div(f"Last data: {latest_date}", className="text-muted"),
    ])


@callback(
    Output("portfolio-snapshot-content", "children"),
    Input("today-content", "children"),
)
def load_portfolio_snapshot(_):
    """Load portfolio snapshot data."""
    summary = get_active_portfolios_summary(exclude_watchlist=True)
    positions = get_active_current_positions(exclude_watchlist=True)

    if not positions:
        return html.Div("No positions", className="text-muted")

    # Get latest prices for all tickers
    tickers = list(set(p["ticker"] for p in positions))
    latest_prices = get_latest_prices(tickers)

    # Calculate total market value
    total_market_value = 0.0
    for pos in positions:
        price = latest_prices.get(pos["ticker"], 0.0)
        total_market_value += pos["shares"] * price

    total_value = total_market_value + summary["total_cash_balance"]

    return html.Div([
        html.Div([
            html.Span("Total Value: ", className="text-muted"),
            html.Span(f"€{total_value:,.2f}", style={"fontWeight": "600"}),
        ]),
        html.Div([
            html.Span("Cash: ", className="text-muted"),
            html.Span(f"€{summary['total_cash_balance']:,.2f}"),
        ]),
        html.Div([
            html.Span("Positions: ", className="text-muted"),
            html.Span(f"{len(tickers)} assets"),
        ]),
    ])


def _gather_brief_context() -> dict:
    """Gather structured context for AI brief generation (multi-portfolio aggregation)."""
    try:
        # Get active portfolio IDs (exclude watchlist)
        portfolio_ids = get_active_portfolio_ids(exclude_watchlist=True)

        if not portfolio_ids:
            return _empty_brief_context()

        # Aggregate positions and cash across all active portfolios
        all_positions = []
        total_cash_balance = 0.0

        for portfolio_id in portfolio_ids:
            trades = list_trades(portfolio_id, limit=1000)
            positions = compute_positions(trades)
            cash_movements = list_cash_movements(portfolio_id, limit=1000)
            cash_balance = compute_cash_balance(cash_movements, trades)

            all_positions.extend(positions)
            total_cash_balance += cash_balance

        # Calculate total value
        tickers = list(set(p["ticker"] for p in all_positions))
        prices = get_latest_prices(tickers) if tickers else {}

        # Aggregate shares per ticker across portfolios
        ticker_shares = {}
        for p in all_positions:
            ticker = p["ticker"]
            ticker_shares[ticker] = ticker_shares.get(ticker, 0.0) + p["shares"]

        total_market_value = sum(ticker_shares.get(t, 0) * prices.get(t, 0) for t in tickers)
        total_value = total_market_value + total_cash_balance
        cash_pct = (total_cash_balance / total_value * 100) if total_value > 0 else 0

        # Use first portfolio's policy as reference (or could aggregate)
        policy = load_policy_snapshot(portfolio_ids[0]).get("policy", {})
        cash_target = policy.get("cash_target_pct", 0)

        # Portfolio name
        portfolio_name = "All Portfolios" if len(portfolio_ids) > 1 else "Portfolio"

    except Exception:
        return _empty_brief_context()

    # Basic context
    context = {
        "portfolio_name": portfolio_name,
        "total_value": f"€{total_value:,.0f}",
        "cash_value": f"€{total_cash_balance:,.0f}",
        "cash_pct": f"{cash_pct:.1f}%",
        "number_positions": len(tickers),
        "drift_summary": {
            "cash_status": "OK" if abs(cash_pct - cash_target) < 5 else "WARN" if abs(cash_pct - cash_target) < 10 else "BREACH",
        },
        "signals_summary": {
            "priority_count": 0,  # Computed in _compute_signals_status
            "sell_count": 0,
        },
        "data_quality": {
            "missing_prices_count": sum(1 for t in tickers if t not in prices),
        },
    }

    return context


def _empty_brief_context() -> dict:
    """Return empty context when no portfolios are available."""
    return {
        "portfolio_name": "No Portfolios",
        "total_value": "€0",
        "cash_value": "€0",
        "cash_pct": "0%",
        "number_positions": 0,
        "drift_summary": {"cash_status": "OK"},
        "signals_summary": {"priority_count": 0, "sell_count": 0},
        "data_quality": {"missing_prices_count": 0},
    }


def _generate_fallback_brief(context: dict) -> str:
    """Generate deterministic fallback brief when AI fails."""
    return f"""Hi Gunther,

Your portfolio stands at {context['total_value']} with {context['number_positions']} positions and {context['cash_pct']} cash. All systems are operational and no urgent actions are required today.

Action points:
- Hold current positions
- Monitor market conditions
- Review cash allocation if needed
- Stay disciplined with your long-term plan"""


def _call_local_ai(context: dict, ai_settings: dict) -> str | None:
    """Call local LLM to generate brief."""
    try:
        base_url = ai_settings.get("base_url", "http://localhost:11434")
        model = ai_settings.get("model", "llama3.1:8b")
        timeout_ms = ai_settings.get("timeout_ms", 30000)

        system_message = "You are a conservative long-term portfolio manager. Be concise, factual, and calm. No hype. No trading encouragement."

        user_message = f"""Write a short daily portfolio briefing.

Rules:
- Start with: 'Hi Gunther,'
- Write 2–4 sentences summarizing portfolio status and risk
- Then write 'Action points:' followed by 3–5 bullets
- Each bullet must start with a verb (Add, Hold, Review, Trim, Fix, Ignore)
- If there is no urgent issue, explicitly say: 'No action needed today.'
- Never encourage frequent trading.

Context:
{json.dumps(context, indent=2)}"""

        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": user_message,
                "system": system_message,
                "stream": False,
            },
            timeout=timeout_ms / 1000,
        )

        if response.status_code == 200:
            result = response.json()
            return result.get("response", "").strip()

        return None

    except Exception:
        return None


@callback(
    Output("ai-brief-content", "children"),
    Output("ai-brief-cache", "data"),
    Output("ai-brief-status", "data"),
    Output("ai-brief-status-text", "children"),
    Input("today-content", "children"),
    Input("ai-brief-refresh-btn", "n_clicks"),
    State("ai-brief-cache", "data"),
    prevent_initial_call=False,
)
def generate_ai_brief(_, refresh_clicks, cache):
    """Generate or retrieve cached AI brief (multi-portfolio)."""
    current_time = time.time()
    cache_duration = 60 * 60  # 60 minutes

    # Get active portfolio IDs for cache key
    portfolio_ids = get_active_portfolio_ids(exclude_watchlist=True)
    cache_key = ",".join(map(str, sorted(portfolio_ids)))  # Stable cache key

    # Check cache validity
    cached_text = cache.get("text")
    cached_time = cache.get("timestamp", 0)
    cached_key = cache.get("portfolio_key")

    is_cache_valid = (
        cached_text is not None
        and cached_key == cache_key
        and (current_time - cached_time) < cache_duration
        and refresh_clicks == 0
    )

    if is_cache_valid:
        # Return cached brief
        content = _format_brief_content(cached_text)
        status_text = f"Status: Updated {int((current_time - cached_time) / 60)}m ago"
        return content, cache, "idle", status_text

    # Generate new brief
    try:
        # Get AI settings from first portfolio (or could be global settings)
        ai_settings = {}
        if portfolio_ids:
            ai_settings = get_ai_settings(portfolio_ids[0])

        if not ai_settings or not ai_settings.get("enabled"):
            # AI disabled, use fallback
            context = _gather_brief_context()
            brief_text = _generate_fallback_brief(context)
            content = _format_brief_content(brief_text)
            new_cache = {"text": brief_text, "timestamp": current_time, "portfolio_key": cache_key}
            return content, new_cache, "idle", "Status: AI disabled (fallback used)"

        # Gather context
        context = _gather_brief_context()

        # Call AI
        brief_text = _call_local_ai(context, ai_settings)

        if brief_text:
            # Success
            content = _format_brief_content(brief_text)
            new_cache = {"text": brief_text, "timestamp": current_time, "portfolio_key": cache_key}
            return content, new_cache, "idle", "Status: Updated just now"
        else:
            # AI failed, use fallback
            brief_text = _generate_fallback_brief(context)
            content = _format_brief_content(brief_text)
            new_cache = {"text": brief_text, "timestamp": current_time, "portfolio_key": cache_key}
            return content, new_cache, "error", "Status: Error (fallback used)"

    except Exception:
        # Error occurred, use fallback
        context = _gather_brief_context()
        brief_text = _generate_fallback_brief(context)
        content = _format_brief_content(brief_text)
        new_cache = {"text": brief_text, "timestamp": current_time, "portfolio_key": cache_key}
        return content, new_cache, "error", "Status: Error (fallback used)"


def _format_brief_content(brief_text: str) -> html.Div:
    """Format the brief text into HTML components."""
    lines = brief_text.strip().split("\n")

    children = []
    in_action_points = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.lower().startswith("action points"):
            in_action_points = True
            children.append(
                html.Div(
                    "Action points",
                    className="today-ai-label",
                    style={"marginTop": "16px", "marginBottom": "8px", "fontSize": "13px", "fontWeight": "600"},
                )
            )
        elif in_action_points and line.startswith("-"):
            children.append(
                html.Div(
                    line,
                    style={"color": "white", "marginLeft": "8px", "marginBottom": "4px"},
                )
            )
        elif line.lower().startswith("hi gunther"):
            children.append(
                html.Div(
                    line,
                    style={"fontSize": "18px", "fontWeight": "600", "color": "white", "marginBottom": "12px"},
                )
            )
        else:
            children.append(
                html.Div(
                    line,
                    style={"color": "white", "marginBottom": "8px", "lineHeight": "1.6"},
                )
            )

    return html.Div(children=children)


@callback(
    Output("today-markets-primary", "children"),
    Output("today-markets-sub", "children"),
    Output("today-health-primary", "children"),
    Output("today-health-sub", "children"),
    Output("today-cash-primary", "children"),
    Output("today-cash-sub", "children"),
    Output("today-signals-primary", "children"),
    Output("today-signals-sub", "children"),
    Output("today-posture-line", "children"),
    Output("today-markets-card-wrapper", "className"),
    Output("today-health-card-wrapper", "className"),
    Output("today-cash-card-wrapper", "className"),
    Output("today-signals-card-wrapper", "className"),
    Output("ai-brief-card", "className", allow_duplicate=True),
    Output("ai-brief-toggle-btn", "children", allow_duplicate=True),
    Output("ai-brief-collapsed-state", "data", allow_duplicate=True),
    Input("url", "pathname"),
    Input("ai-brief-refresh-btn", "n_clicks"),
    prevent_initial_call='initial_duplicate',
)
def update_status_cards(pathname, _refresh_clicks):
    """Update all portfolio status cards and posture line (multi-portfolio aggregation)."""
    if pathname not in ["/", "/today"]:
        raise PreventUpdate

    try:
        # Get active portfolio IDs
        portfolio_ids = get_active_portfolio_ids(exclude_watchlist=True)
        if not portfolio_ids:
            return _empty_status_cards()

        # Aggregate data across all active portfolios
        all_positions = []
        total_cash_balance = 0.0

        for portfolio_id in portfolio_ids:
            trades = list_trades(portfolio_id, limit=1000)
            positions = compute_positions(trades)
            cash_movements = list_cash_movements(portfolio_id, limit=1000)
            cash_balance = compute_cash_balance(cash_movements, trades)

            all_positions.extend(positions)
            total_cash_balance += cash_balance

        # Aggregate tickers and calculate total value
        tickers = list(set(p["ticker"] for p in all_positions))
        prices = get_latest_prices(tickers) if tickers else {}

        # Aggregate shares per ticker
        ticker_shares = {}
        for p in all_positions:
            ticker = p["ticker"]
            ticker_shares[ticker] = ticker_shares.get(ticker, 0.0) + p["shares"]

        total_market_value = sum(ticker_shares.get(t, 0) * prices.get(t, 0) for t in tickers)
        total_value = total_market_value + total_cash_balance
        cash_pct = (total_cash_balance / total_value * 100) if total_value > 0 else 0

        # Use first portfolio's policy as reference
        policy = load_policy_snapshot(portfolio_ids[0]).get("policy", {})
        cash_min = policy.get("cash_min_pct", 0)
        cash_max = policy.get("cash_max_pct", 100)
        cash_target = policy.get("cash_target_pct", 0)

        # === 1. Markets Status ===
        markets_status, markets_sub = _compute_markets_status()

        # === 2. Portfolio Health ===
        health_status, health_sub = _compute_health_status(policy, cash_pct, cash_min, cash_max)

        # === 3. Cash & Allocation ===
        cash_status, cash_sub = _compute_cash_status(cash_pct, cash_min, cash_max, cash_target)

        # === 4. Signals & Risk ===
        signals_status, signals_sub, priority_count, sell_count = _compute_signals_status()

        # === Suggested Posture ===
        posture = _compute_posture(health_status, priority_count, sell_count, cash_pct, cash_min)

        # === Compute Severity Levels ===
        markets_severity = "bad" if markets_status == "Defensive" else "info"

        # Health: bad if "Stressed", ok if "Stable", else info
        health_severity = "bad" if health_status == "Stressed" else ("warn" if health_status == "Watch" else "ok")

        # Cash: warn if below min, ok otherwise
        cash_severity = "warn" if cash_pct < cash_min else "ok"

        # Signals: bad if sells > 0, warn if priority > 0, else ok
        if sell_count > 0:
            signals_severity = "bad"
        elif priority_count > 0:
            signals_severity = "warn"
        else:
            signals_severity = "ok"

        # Build className strings for card wrappers
        markets_class = f"status-card-clickable status-card-{markets_severity}"
        health_class = f"status-card-clickable status-card-{health_severity}"
        cash_class = f"status-card-clickable status-card-{cash_severity}"
        signals_class = f"status-card-clickable status-card-{signals_severity}"

        # Auto-expand AI brief if breaches or sells detected
        should_expand = (health_status == "Stressed") or (sell_count > 0)
        ai_brief_class = "card today-ai-brief ai-brief-expanded" if should_expand else "card today-ai-brief ai-brief-collapsed"
        ai_brief_btn_text = "Collapse" if should_expand else "Expand"
        ai_brief_state = not should_expand  # Store is "is_collapsed"

        return (
            markets_status, markets_sub,
            health_status, health_sub,
            cash_status, cash_sub,
            signals_status, signals_sub,
            posture,
            markets_class,
            health_class,
            cash_class,
            signals_class,
            ai_brief_class,
            ai_brief_btn_text,
            ai_brief_state,
        )

    except Exception as e:
        # Fallback on error
        return _empty_status_cards()


def _empty_status_cards():
    """Return empty/error state for all status cards."""
    return (
        "Unknown", "Data unavailable",
        "Unknown", "Data unavailable",
        "N/A", "Data unavailable",
        "N/A", "Data unavailable",
        "→ Suggested posture today: Unable to compute (data unavailable)",
        "status-card-clickable status-card-info",  # markets
        "status-card-clickable status-card-info",  # health
        "status-card-clickable status-card-info",  # cash
        "status-card-clickable status-card-info",  # signals
        "card today-ai-brief ai-brief-collapsed",  # AI brief class
        "Expand",  # AI brief button text
        True,  # AI brief collapsed state
    )


def _compute_markets_status() -> tuple[str, str]:
    """Compute market regime status using benchmark trend."""
    try:
        # Get first benchmark
        benchmarks = list_benchmarks()
        if not benchmarks:
            return "Unknown", "No benchmarks configured"

        benchmark = benchmarks[0]
        benchmark_id = benchmark["benchmark_id"]
        ticker = benchmark.get("ticker", "")

        if not ticker:
            return "Unknown", "Benchmark has no ticker"

        # Get 90 days of EOD data
        from datetime import timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

        # Ensure cached
        ensure_benchmark_eod_cached(benchmark_id, ticker, start_date, end_date)
        bars = get_benchmark_eod(benchmark_id, start_date, end_date)

        if len(bars) < 50:
            return "Unknown", "Insufficient price data"

        # Calculate EMA20 and EMA50
        closes = [b["close"] for b in bars]
        ema20 = _calculate_ema(closes, 20)
        ema50 = _calculate_ema(closes, 50)

        if ema20 is None or ema50 is None:
            return "Neutral", "Calculating trend..."

        # Determine regime
        if ema20 > ema50 * 1.02:  # 2% above
            return "Bullish", "Trend is positive"
        elif ema20 < ema50 * 0.98:  # 2% below
            return "Defensive", "Trend weakening"
        else:
            return "Neutral", "No clear trend"

    except Exception:
        return "Unknown", "Calculation error"


def _calculate_ema(prices: list[float], period: int) -> float | None:
    """Calculate simple EMA for the last value."""
    if len(prices) < period:
        return None

    # Simple EMA calculation
    alpha = 2 / (period + 1)
    ema = sum(prices[:period]) / period  # Start with SMA

    for price in prices[period:]:
        ema = price * alpha + ema * (1 - alpha)

    return ema


def _compute_health_status(policy: dict, cash_pct: float, cash_min: float, cash_max: float) -> tuple[str, str]:
    """Compute portfolio health based on policy drift."""
    try:
        breaches = 0
        warnings = 0

        # Check cash drift
        if cash_pct < cash_min:
            breaches += 1
        elif cash_pct > cash_max:
            breaches += 1
        elif abs(cash_pct - policy.get("cash_target_pct", 0)) > 5:
            warnings += 1

        if breaches > 0:
            return "Stressed", f"{breaches} policy breach(es) detected"
        elif warnings > 0:
            return "Watch", f"{warnings} area(s) near limits"
        else:
            return "Stable", "No policy breaches"

    except Exception:
        return "Watch", "Incomplete data"


def _compute_cash_status(cash_pct: float, cash_min: float, cash_max: float, cash_target: float) -> tuple[str, str]:
    """Compute cash allocation status."""
    try:
        if cash_pct < cash_min:
            return f"{cash_pct:.0f}% (below minimum)", "Cash below minimum — pause adds"
        elif cash_pct > cash_max:
            return f"{cash_pct:.0f}% (above maximum)", "Cash too high — deploy capital"
        elif abs(cash_pct - cash_target) <= 5:
            return f"{cash_pct:.0f}% (within target)", "Ready for next contribution"
        else:
            return f"{cash_pct:.0f}% (near target)", "Allocation acceptable"

    except Exception:
        return "N/A", "Cash data unavailable"


def _compute_signals_status() -> tuple[str, str, int, int]:
    """Compute signals and risk summary (aggregated across active portfolios)."""
    try:
        # Get active portfolio IDs
        portfolio_ids = get_active_portfolio_ids(exclude_watchlist=True)
        if not portfolio_ids:
            return "N/A", "No portfolios", 0, 0

        # Aggregate signal counts across all portfolios
        total_buy_signals = 0
        total_sell_signals = 0
        total_hold_signals = 0
        total_data_errors = 0

        # Collect all unique tickers across portfolios (for batched price fetch)
        all_tickers = set()
        portfolio_data = []

        for portfolio_id in portfolio_ids:
            # Get positions for this portfolio
            trades = list_trades(portfolio_id, limit=1000)
            positions = compute_positions(trades)

            # Get watchlist for this portfolio
            watchlist = list_watchlist(portfolio_id)

            # Get strategy assignments for this portfolio
            assignment_map = get_assignment_map(portfolio_id)

            if not assignment_map:
                continue  # No strategies assigned, skip this portfolio

            # Collect tickers and store portfolio data
            tickers_in_portfolio = {pos["ticker"] for pos in positions if pos["ticker"] in assignment_map}
            tickers_in_portfolio.update(entry["ticker"] for entry in watchlist if entry["ticker"] in assignment_map)
            all_tickers.update(tickers_in_portfolio)

            portfolio_data.append({
                "portfolio_id": portfolio_id,
                "trades": trades,
                "positions": positions,
                "watchlist": watchlist,
                "assignment_map": assignment_map,
            })

        # Batch fetch all prices at once (performance optimization)
        if all_tickers:
            prices_dict, _failures = get_latest_daily_closes_cached(list(all_tickers))
        else:
            prices_dict = {}

        # Now evaluate signals using pre-fetched data
        for pdata in portfolio_data:
            portfolio_id = pdata["portfolio_id"]
            trades = pdata["trades"]
            positions = pdata["positions"]
            watchlist = pdata["watchlist"]
            assignment_map = pdata["assignment_map"]

            # Evaluate position signals
            for pos in positions:
                ticker = pos["ticker"]
                if ticker not in assignment_map:
                    continue

                strategy_id = assignment_map[ticker]
                saved_strategy = get_saved_strategy_by_id(portfolio_id, strategy_id)

                if not saved_strategy:
                    continue

                # Use pre-fetched price
                current_price = prices_dict.get(ticker)

                if current_price is None:
                    total_data_errors += 1
                    continue

                # Evaluate signal
                signal_result = evaluate_position_signal(
                    ticker=ticker,
                    saved_strategy=saved_strategy,
                    current_price=current_price,
                    trades=trades,
                )

                signal = signal_result.get("signal", "DATA")
                if signal == "BUY":
                    total_buy_signals += 1
                elif signal == "SELL":
                    total_sell_signals += 1
                elif signal == "HOLD":
                    total_hold_signals += 1
                else:  # DATA
                    total_data_errors += 1

            # Evaluate watchlist signals
            for entry in watchlist:
                ticker = entry["ticker"]
                if ticker not in assignment_map:
                    continue

                strategy_id = assignment_map[ticker]
                saved_strategy = get_saved_strategy_by_id(portfolio_id, strategy_id)

                if not saved_strategy:
                    continue

                # Evaluate watchlist signal
                signal_result = evaluate_watchlist_signal(
                    ticker=ticker,
                    saved_strategy=saved_strategy,
                )

                signal = signal_result.get("signal", "DATA")
                if signal == "BUY":
                    total_buy_signals += 1
                elif signal == "HOLD":
                    total_hold_signals += 1
                else:  # DATA
                    total_data_errors += 1

        # Determine display based on aggregated counts
        if total_buy_signals > 0:
            return f"{total_buy_signals} priority buys", "", total_buy_signals, total_sell_signals
        elif total_sell_signals > 0:
            return "Review positions", f"{total_sell_signals} SELL signal(s)", total_buy_signals, total_sell_signals
        else:
            monitor_count = total_hold_signals
            return "No urgent actions", f"{monitor_count} positions to monitor", total_buy_signals, total_sell_signals

    except Exception as e:
        return "N/A", "Signals error", 0, 0


def _compute_posture(health_status: str, priority_count: int, sell_count: int, cash_pct: float, cash_min: float) -> str:
    """Compute suggested posture based on portfolio state."""
    try:
        if health_status == "Stressed":
            return "→ Suggested posture today: Reduce risk gradually. No new buying until breaches resolved."
        elif priority_count > 0 and cash_pct >= cash_min:
            return "→ Suggested posture today: Add only with new cash to top priority names."
        elif sell_count > 0:
            return "→ Suggested posture today: Review SELL signals. Consider trims if aligned with plan."
        else:
            return "→ Suggested posture today: Do nothing. Stay invested."

    except Exception:
        return "→ Suggested posture today: Unable to compute (data error)"
