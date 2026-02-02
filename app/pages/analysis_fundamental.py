from __future__ import annotations

import re
import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate
from datetime import datetime

from app.db.benchmarks_repo import (
    list_benchmarks,
    get_benchmark_snapshot_tickers,
    get_ticker_snapshot_detail,
    get_benchmark_tickers_with_fundamentals,
)
from app.db.rebalance_repo import get_ai_settings

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

# AI analysis cache (LRU)
_ai_cache = {}
_ai_cache_order = []
MAX_CACHE_SIZE = 100


def get_cached_ai_analysis(ticker, updated_at):
    """Get cached AI analysis or None."""
    cache_key = (ticker, updated_at[:10] if updated_at else ticker)
    if cache_key in _ai_cache:
        _ai_cache_order.remove(cache_key)
        _ai_cache_order.append(cache_key)
        return _ai_cache[cache_key]
    return None


def cache_ai_analysis(ticker, updated_at, content):
    """Cache AI analysis with LRU eviction."""
    cache_key = (ticker, updated_at[:10] if updated_at else ticker)

    if len(_ai_cache) >= MAX_CACHE_SIZE:
        oldest_key = _ai_cache_order.pop(0)
        del _ai_cache[oldest_key]

    _ai_cache[cache_key] = content
    _ai_cache_order.append(cache_key)


def safe_get(row, keys):
    """Try multiple key names, return first non-None."""
    key_list = keys if isinstance(keys, list) else [keys]
    for k in key_list:
        if k in row and row[k] is not None:
            return row[k]
    return None


def fmt_pct(val):
    """Format percentage or return N/A."""
    if val is None:
        return "N/A"
    return f"{val*100:.1f}%"


def fmt_ratio(val):
    """Format ratio or return N/A."""
    if val is None:
        return "N/A"
    return f"{val:.2f}"


def calc_signal(val, thresholds):
    """Calculate signal emoji based on value and thresholds.
    thresholds = {"green": x, "orange": y, "direction": "higher|lower"}
    """
    if val is None:
        return "—"
    direction = thresholds.get("direction", "higher")
    if direction == "higher":
        if val >= thresholds.get("green", 10):
            return "🟢"
        elif val >= thresholds.get("orange", 5):
            return "🟠"
        else:
            return "🔴"
    else:  # lower is better
        if val <= thresholds.get("green", 2):
            return "🟢"
        elif val <= thresholds.get("orange", 4):
            return "🟠"
        else:
            return "🔴"


def build_growth_metrics(detail):
    """Build growth & cash flow metrics table (future-proof)."""
    config = [
        ("Revenue Growth YoY", ["revenue_growth_yoy", "revenue_yoy"], fmt_pct,
         {"direction": "higher", "green": 0.10, "orange": 0.02}),
        ("EPS Growth YoY", ["eps_growth_yoy", "earnings_growth_yoy"], fmt_pct,
         {"direction": "higher", "green": 0.12, "orange": 0.00}),
        ("FCF Margin", ["fcf_margin", "free_cash_flow_margin"], fmt_pct,
         {"direction": "higher", "green": 0.10, "orange": 0.05}),
        ("FCF Growth YoY", ["fcf_growth_yoy"], fmt_pct,
         {"direction": "higher", "green": 0.10, "orange": 0.02}),
    ]

    rows = []
    for metric_name, keys, format_fn, thresholds in config:
        val = safe_get(detail, keys)
        if val is None:
            continue  # Skip missing metrics
        disp = format_fn(val)
        signal = calc_signal(val, thresholds)
        rows.append({"metric": metric_name, "value": disp, "signal": signal})
    return rows


def build_balance_sheet_metrics(detail):
    """Build balance sheet & solvency metrics table (future-proof)."""
    config = [
        ("Net Debt / EBITDA", ["net_debt_to_ebitda"], fmt_ratio,
         {"direction": "lower", "green": 2.0, "orange": 4.0}),
        ("Interest Coverage", ["interest_coverage"], fmt_ratio,
         {"direction": "higher", "green": 6.0, "orange": 3.0}),
        ("Current Ratio", ["current_ratio"], fmt_ratio,
         {"direction": "higher", "green": 1.5, "orange": 1.0}),
        ("Debt / Equity", ["debt_to_equity", "debt_to_assets"], fmt_ratio,
         {"direction": "lower", "green": 1.0, "orange": 2.0}),
        ("Shares Outstanding Growth", ["shares_out_growth_yoy"], fmt_pct,
         {"direction": "lower", "green": 0.00, "orange": 0.03}),
    ]

    rows = []
    for metric_name, keys, format_fn, thresholds in config:
        val = safe_get(detail, keys)
        if val is None:
            continue
        disp = format_fn(val)
        signal = calc_signal(val, thresholds)
        rows.append({"metric": metric_name, "value": disp, "signal": signal})
    return rows


def layout() -> html.Div:
    return html.Div(
        children=[
            # Stores
            dcc.Store(id="fundamental-active-ticker", data=None),
            dcc.Store(id="fundamental-ai-job-status", data=None),
            dcc.Store(id="fund-ai-payload", data=None),
            dcc.Store(id="fund-finder-page", data=0),
            dcc.Store(id="fundamentals-finder-store", data=None),
            dcc.Store(id="fundamental-active-tab", data="finder"),

            # Page header
            html.Div(
                className="page-header",
                children=[
                    html.Div(
                        children=[
                            html.H2("Analysis – Fundamental", style={"margin": "0"}),
                            html.Div(
                                "Investigate ticker fundamentals using stored benchmark snapshot data.",
                                className="page-subtitle",
                            ),
                        ]
                    ),
                    html.Div(
                        className="page-header-actions",
                        children=[
                            # Finder controls (visible by default)
                            html.Div(
                                id="fund-header-finder",
                                style={"display": "flex", "gap": "20px"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Benchmark", className="field-label"),
                                            dcc.Dropdown(
                                                id="fundamental-benchmark",
                                                options=[],
                                                value=None,
                                                placeholder="Select benchmark",
                                                clearable=True,
                                                style={"minWidth": "220px"},
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div("Search", className="field-label"),
                                            dcc.Input(
                                                id="fund-finder-search",
                                                type="text",
                                                placeholder="Search ticker, name, sector, label…",
                                                debounce=True,
                                                style={"minWidth": "280px"},
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                            # Breakdown controls (hidden by default)
                            html.Div(
                                id="fund-header-breakdown",
                                style={"display": "none"},
                                children=[
                                    html.Div(
                                        children=[
                                            html.Div("Manual Ticker", className="field-label"),
                                            dcc.Input(
                                                id="fund-breakdown-ticker-input",
                                                type="text",
                                                placeholder="Enter ticker (e.g., AAPL)",
                                                style={"minWidth": "160px"},
                                            ),
                                        ]
                                    ),
                                    html.Div(
                                        children=[
                                            html.Div(style={"height": "20px"}),  # Spacer for alignment
                                            html.Button(
                                                "Load",
                                                id="fund-breakdown-load-btn",
                                                className="btn-secondary",
                                                style={"marginTop": "0px"},
                                            ),
                                        ]
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Status bar
            html.Div(
                id="fundamental-status-bar",
                className="status-bar",
                children="Select a benchmark to load candidates.",
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
                            dbc.NavLink(
                                "Finder",
                                id="fundamental-nav-finder",
                                active=True,
                                style=PILL_ACTIVE_STYLE,
                            ),
                            dbc.NavLink(
                                "Ticker Breakdown",
                                id="fundamental-nav-breakdown",
                                active=False,
                                style=PILL_INACTIVE_STYLE,
                            ),
                        ],
                    ),
                ],
            ),

            # Panel 1: Finder
            html.Div(
                id="fundamental-panel-finder",
                style={"display": "block"},
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Ticker Candidates", className="card-title"),
                            DataTable(
                                id="fundamental-finder-table",
                                columns=[
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Name", "id": "ticker_name"},
                                    {"name": "Sector", "id": "sector"},
                                    {"name": "Label", "id": "fundamental_label"},
                                    {"name": "Durability", "id": "durability_disp"},
                                    {"name": "Total", "id": "bench_score_total", "type": "numeric", "format": {"specifier": ".0f"}},
                                    {"name": "Quality", "id": "quality_disp"},
                                    {"name": "Safety", "id": "safety_disp"},
                                    {"name": "Value", "id": "value_disp"},
                                    {"name": "Confidence", "id": "bench_confidence"},
                                    {"name": "Updated", "id": "updated_at"},
                                ],
                                data=[],
                                page_action="custom",
                                page_current=0,
                                page_size=20,
                                sort_action="custom",
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                                style_data_conditional=[
                                    {
                                        "if": {"column_id": "ticker"},
                                        "cursor": "pointer",
                                        "textDecoration": "underline",
                                        "color": "var(--accent)",
                                    },
                                    {
                                        "if": {"filter_query": "{fundamental_label} = INTERESTING", "column_id": "fundamental_label"},
                                        "color": "var(--ok)",
                                        "fontWeight": "600",
                                    },
                                    {
                                        "if": {"filter_query": "{fundamental_label} = EXPENSIVE", "column_id": "fundamental_label"},
                                        "color": "var(--warning)",
                                    },
                                    {
                                        "if": {"filter_query": "{fundamental_label} = DOUBTFUL", "column_id": "fundamental_label"},
                                        "color": "var(--text-muted)",
                                    },
                                    {
                                        "if": {"filter_query": "{fundamental_label} = AVOID", "column_id": "fundamental_label"},
                                        "color": "var(--danger)",
                                    },
                                ],
                            ),
                            html.Div(
                                className="custom-pager",
                                children=[
                                    html.Button("<<", id="fund-pager-first"),
                                    html.Button("<", id="fund-pager-prev"),
                                    html.Button(">", id="fund-pager-next"),
                                    html.Button(">>", id="fund-pager-last"),
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Panel 2: Ticker Breakdown
            html.Div(
                id="fundamental-panel-breakdown",
                style={"display": "none"},
                children=[
                    html.Div(id="fundamental-breakdown-content"),
                ],
            ),
        ],
        style={"maxWidth": "1100px"},
    )


# Callback: populate benchmark dropdown
@callback(
    Output("fundamental-benchmark", "options"),
    Input("url", "pathname"),
)
def populate_benchmark_dropdown(pathname):
    if pathname != "/analysis/fundamental":
        raise PreventUpdate

    benchmarks = list_benchmarks()
    return [{"label": bm["name"], "value": bm["benchmark_id"]} for bm in benchmarks]


# Callback: toggle header actions based on active tab
@callback(
    Output("fund-header-finder", "style"),
    Output("fund-header-breakdown", "style"),
    Input("fundamental-active-tab", "data"),
)
def toggle_header_actions(active_tab):
    """Show/hide header actions based on active tab."""
    if active_tab == "finder":
        return {"display": "flex", "gap": "20px"}, {"display": "none"}
    else:  # breakdown
        return {"display": "none"}, {"display": "flex", "gap": "20px"}


# Callback: load finder table (store full dataset)
@callback(
    Output("fundamentals-finder-store", "data"),
    Output("fundamental-status-bar", "children"),
    Output("fundamental-finder-table", "page_current"),
    Input("fundamental-benchmark", "value"),
    Input("fund-finder-search", "value"),
)
def load_finder_table(benchmark_id, search_text):
    if not benchmark_id:
        return [], "Select a benchmark to load candidates.", 0

    tickers = get_benchmark_snapshot_tickers(benchmark_id)

    if not tickers:
        return [], "No snapshot data available. Go to Market → Breakdown to refresh.", 0

    # Compute sector averages for Quality/Safety/Value
    sector_stats = {}
    for row in tickers:
        sector = row.get("sector")
        if not sector:
            continue
        if sector not in sector_stats:
            sector_stats[sector] = {"quality": [], "safety": [], "value": []}

        if row.get("bench_score_quality") is not None:
            sector_stats[sector]["quality"].append(row["bench_score_quality"])
        if row.get("bench_score_safety") is not None:
            sector_stats[sector]["safety"].append(row["bench_score_safety"])
        if row.get("bench_score_value") is not None:
            sector_stats[sector]["value"].append(row["bench_score_value"])

    sector_avgs = {}
    for sector, stats in sector_stats.items():
        sector_avgs[sector] = {
            "quality": sum(stats["quality"]) / len(stats["quality"]) if len(stats["quality"]) >= 2 else None,
            "safety": sum(stats["safety"]) / len(stats["safety"]) if len(stats["safety"]) >= 2 else None,
            "value": sum(stats["value"]) / len(stats["value"]) if len(stats["value"]) >= 2 else None,
        }

    # Add display strings for Quality/Safety/Value columns + Durability
    for row in tickers:
        sector = row.get("sector")
        sector_avg = sector_avgs.get(sector, {})

        for dimension in ["quality", "safety", "value"]:
            score = row.get(f"bench_score_{dimension}")
            avg = sector_avg.get(dimension)

            if score is None:
                row[f"{dimension}_disp"] = "—"
            elif avg is None or avg == 0:
                row[f"{dimension}_disp"] = f"{round(score)} —"
            else:
                delta_pct = (score - avg) / avg * 100
                arrow = "▲" if delta_pct >= 0 else "▼"
                row[f"{dimension}_disp"] = f"{round(score)} {arrow}{abs(round(delta_pct))}%"

        # Compute durability = (quality + safety) / 2
        quality = row.get("bench_score_quality")
        safety = row.get("bench_score_safety")
        if quality is not None and safety is not None:
            durability = (quality + safety) / 2
            row["durability"] = durability
            # Stars: >=70 => ★★★, 55-69 => ★★☆, 40-54 => ★☆☆, <40 => ☆☆☆
            if durability >= 70:
                stars = "★★★"
            elif durability >= 55:
                stars = "★★☆"
            elif durability >= 40:
                stars = "★☆☆"
            else:
                stars = "☆☆☆"
            row["durability_disp"] = f"{stars} {round(durability)}"
        else:
            row["durability"] = None
            row["durability_disp"] = "—"

        # Format updated_at to YYYY-MM-DD only
        if row.get("updated_at"):
            row["updated_at"] = row["updated_at"][:10]

    # Sort by label priority, then total score desc
    label_order = {"INTERESTING": 0, "DOUBTFUL": 1, "EXPENSIVE": 2, "AVOID": 3, "missing": 4, None: 5}

    sorted_tickers = sorted(
        tickers,
        key=lambda x: (
            label_order.get(x.get("fundamental_label"), 5),
            -(x.get("bench_score_total") or 0),
        ),
    )

    # Apply search filter with heuristic parser
    if search_text and search_text.strip():
        query = search_text.strip()
        query_lower = query.lower()

        # Parse heuristic rules
        numeric_filters = []
        text_query = query_lower

        # Detect "durable" => durability >= 70
        if "durable" in query_lower and "not durable" not in query_lower:
            numeric_filters.append(("durability", ">=", 70))
            text_query = ""
        # Detect "fragile" or "not durable" => durability < 55
        elif "fragile" in query_lower or "not durable" in query_lower:
            numeric_filters.append(("durability", "<", 55))
            text_query = ""
        else:
            # Parse numeric expressions: field>value, field>=value, field<value, field<=value
            patterns = [
                (r"quality\s*(>=?)\s*(\d+)", "bench_score_quality"),
                (r"safety\s*(>=?)\s*(\d+)", "bench_score_safety"),
                (r"value\s*(>=?)\s*(\d+)", "bench_score_value"),
                (r"confidence\s*(>=?)\s*(\d+)", "bench_confidence"),
                (r"durability\s*(>=?)\s*(\d+)", "durability"),
                (r"quality\s*(<=?)\s*(\d+)", "bench_score_quality"),
                (r"safety\s*(<=?)\s*(\d+)", "bench_score_safety"),
                (r"value\s*(<=?)\s*(\d+)", "bench_score_value"),
                (r"confidence\s*(<=?)\s*(\d+)", "bench_confidence"),
                (r"durability\s*(<=?)\s*(\d+)", "durability"),
            ]

            for pattern, field in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    op = match.group(1)
                    value = int(match.group(2))
                    numeric_filters.append((field, op, value))
                    # Remove from text query
                    text_query = re.sub(pattern, "", text_query).strip()

        # Apply filters
        filtered_tickers = []
        for row in sorted_tickers:
            # Check numeric filters (AND)
            passes_numeric = True
            for field, op, value in numeric_filters:
                field_value = row.get(field)
                if field_value is None:
                    passes_numeric = False
                    break
                if op == ">=" and not (field_value >= value):
                    passes_numeric = False
                    break
                elif op == ">" and not (field_value > value):
                    passes_numeric = False
                    break
                elif op == "<=" and not (field_value <= value):
                    passes_numeric = False
                    break
                elif op == "<" and not (field_value < value):
                    passes_numeric = False
                    break

            if not passes_numeric:
                continue

            # Check text match (OR across text columns)
            if text_query:
                ticker = (row.get("ticker") or "").lower()
                ticker_name = (row.get("ticker_name") or "").lower()
                sector = (row.get("sector") or "").lower()
                label = (row.get("fundamental_label") or "").lower()

                if (text_query in ticker or
                    text_query in ticker_name or
                    text_query in sector or
                    text_query in label):
                    filtered_tickers.append(row)
            else:
                # No text query, only numeric filters applied
                filtered_tickers.append(row)

        return filtered_tickers, f"Found {len(filtered_tickers)} ticker(s) matching '{query}'.", 0

    return sorted_tickers, f"Loaded {len(tickers)} ticker(s) from snapshot.", 0


# Callback: render finder table with pagination and sorting
@callback(
    Output("fundamental-finder-table", "data"),
    Output("fundamental-finder-table", "page_count"),
    Input("fundamentals-finder-store", "data"),
    Input("fundamental-finder-table", "page_current"),
    Input("fundamental-finder-table", "page_size"),
    Input("fundamental-finder-table", "sort_by"),
)
def render_finder_table(store_data, page_current, page_size, sort_by):
    if not store_data:
        return [], 0

    rows = store_data.copy()

    # Apply sorting if requested
    if sort_by and len(sort_by) > 0:
        col_id = sort_by[0]["column_id"]
        direction = sort_by[0]["direction"]
        rows = sorted(
            rows,
            key=lambda r: (r.get(col_id) is None, r.get(col_id) or 0),
            reverse=(direction == "desc")
        )

    # Calculate pagination
    total_rows = len(rows)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    page_current = max(0, min(page_current or 0, total_pages - 1))

    # Slice for current page
    start_idx = page_current * page_size
    end_idx = start_idx + page_size
    page_data = rows[start_idx:end_idx]

    return page_data, total_pages


# Callback: toggle panels
@callback(
    Output("fundamental-panel-finder", "style"),
    Output("fundamental-panel-breakdown", "style"),
    Output("fundamental-nav-finder", "active"),
    Output("fundamental-nav-breakdown", "active"),
    Output("fundamental-nav-finder", "style"),
    Output("fundamental-nav-breakdown", "style"),
    Output("fundamental-active-tab", "data"),
    Input("fundamental-nav-finder", "n_clicks"),
    Input("fundamental-nav-breakdown", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_panels(finder_clicks, breakdown_clicks):
    from dash import ctx

    if not ctx.triggered:
        raise PreventUpdate

    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    if button_id == "fundamental-nav-finder":
        return (
            {"display": "block"},
            {"display": "none"},
            True,
            False,
            PILL_ACTIVE_STYLE,
            PILL_INACTIVE_STYLE,
            "finder",
        )
    elif button_id == "fundamental-nav-breakdown":
        return (
            {"display": "none"},
            {"display": "block"},
            False,
            True,
            PILL_INACTIVE_STYLE,
            PILL_ACTIVE_STYLE,
            "breakdown",
        )
    else:
        raise PreventUpdate


# Callback: click ticker to open breakdown
@callback(
    Output("fundamental-active-ticker", "data"),
    Output("fundamental-panel-finder", "style", allow_duplicate=True),
    Output("fundamental-panel-breakdown", "style", allow_duplicate=True),
    Output("fundamental-nav-finder", "active", allow_duplicate=True),
    Output("fundamental-nav-breakdown", "active", allow_duplicate=True),
    Output("fundamental-nav-finder", "style", allow_duplicate=True),
    Output("fundamental-nav-breakdown", "style", allow_duplicate=True),
    Output("fundamental-active-tab", "data", allow_duplicate=True),
    Input("fundamental-finder-table", "active_cell"),
    State("fundamental-finder-table", "data"),
    prevent_initial_call=True,
)
def click_ticker_to_open(active_cell, data):
    if not active_cell or not data:
        raise PreventUpdate

    # Only navigate when ticker column is clicked
    if active_cell.get("column_id") != "ticker":
        raise PreventUpdate

    row_idx = active_cell["row"]
    ticker = data[row_idx]["ticker"]

    return (
        ticker,
        {"display": "none"},
        {"display": "block"},
        False,
        True,
        PILL_INACTIVE_STYLE,
        PILL_ACTIVE_STYLE,
        "breakdown",
    )


# Callback: load manually entered ticker
@callback(
    Output("fundamental-active-ticker", "data", allow_duplicate=True),
    Input("fund-breakdown-load-btn", "n_clicks"),
    State("fund-breakdown-ticker-input", "value"),
    prevent_initial_call=True,
)
def load_manual_ticker(n_clicks, ticker_input):
    """Load breakdown for manually entered ticker."""
    if not ticker_input or not ticker_input.strip():
        raise PreventUpdate

    # Clean and validate ticker
    ticker = ticker_input.strip().upper()

    # Basic validation: alphanumeric, dots, dashes (e.g., BRK.B, BRK-B)
    if not re.match(r'^[A-Z0-9.\-]+$', ticker):
        raise PreventUpdate

    return ticker


# Callback: load breakdown content
@callback(
    Output("fundamental-breakdown-content", "children"),
    Output("fund-ai-payload", "data"),
    Input("fundamental-active-ticker", "data"),
    State("fundamental-benchmark", "value"),
)
def load_breakdown(ticker, benchmark_id):
    if not ticker:
        return html.Div(
            className="card",
            children=[
                html.Div("No Ticker Selected", className="card-title"),
                html.P("Select a ticker from Finder or enter one manually."),
            ],
        ), None

    if not benchmark_id:
        return html.Div(
            className="card",
            children=[
                html.Div(f"{ticker}", className="card-title"),
                html.P("Please select a benchmark first from the Finder tab."),
            ],
        ), None

    detail = get_ticker_snapshot_detail(benchmark_id, ticker)

    if not detail:
        return html.Div(
            className="card",
            children=[
                html.Div(f"{ticker}", className="card-title"),
                html.P("No snapshot data available for this ticker."),
            ],
        ), None

    # Load all tickers for sector comparison
    all_tickers = get_benchmark_tickers_with_fundamentals(benchmark_id)
    ticker_sector = detail.get("sector")

    # Compute sector averages (within same benchmark + same sector)
    sector_tickers = [t for t in all_tickers if t.get("sector") == ticker_sector] if ticker_sector else []

    def compute_sector_avg(field):
        """Compute sector average for a metric field."""
        if len(sector_tickers) < 5:
            return None
        values = [t.get(field) for t in sector_tickers if t.get(field) is not None]
        return sum(values) / len(values) if values else None

    # Header with label badge
    label = detail.get("fundamental_label", "unknown")
    label_color = {
        "INTERESTING": "var(--ok)",
        "EXPENSIVE": "var(--warning)",
        "DOUBTFUL": "var(--text-muted)",
        "AVOID": "var(--danger)",
    }.get(label, "var(--text)")

    # Compute durability
    quality = detail.get("bench_score_quality")
    safety = detail.get("bench_score_safety")
    durability = round((quality + safety) / 2) if quality is not None and safety is not None else None

    # KPI row: 4 cards (Durability, Quality, Safety, Value)
    kpi_cards = [
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div("Durability", className="hint-text", style={"marginBottom": "5px"}),
                html.Div(str(durability) if durability is not None else "—", style={"fontSize": "24px", "fontWeight": "600"}),
            ],
        ),
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div("Quality", className="hint-text", style={"marginBottom": "5px"}),
                html.Div(str(round(quality)) if quality is not None else "—", style={"fontSize": "24px", "fontWeight": "600"}),
            ],
        ),
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div("Safety", className="hint-text", style={"marginBottom": "5px"}),
                html.Div(str(round(safety)) if safety is not None else "—", style={"fontSize": "24px", "fontWeight": "600"}),
            ],
        ),
        html.Div(
            className="card",
            style={"textAlign": "center"},
            children=[
                html.Div("Value", className="hint-text", style={"marginBottom": "5px"}),
                html.Div(
                    str(round(detail.get("bench_score_value"))) if detail.get("bench_score_value") is not None else "—",
                    style={"fontSize": "24px", "fontWeight": "600"}
                ),
            ],
        ),
    ]

    # Build metrics table
    metrics_config = [
        ("ROE", "roe", "%", "higher"),
        ("Operating Margin", "operating_margins", "%", "higher"),
        ("P/E (TTM)", "pe_ttm", "ratio", "lower"),
        ("Forward P/E", "forward_pe", "ratio", "lower"),
        ("PEG", "peg", "ratio", "lower"),
        ("EV/EBITDA", "ev_to_ebitda", "ratio", "lower"),
        ("Price/Book", "price_to_book", "ratio", "lower"),
        ("Price/Sales", "price_to_sales", "ratio", "lower"),
    ]

    metrics_rows = []
    for metric_name, field, format_type, better_direction in metrics_config:
        ticker_value = detail.get(field)
        sector_avg = compute_sector_avg(field)

        # Format ticker value
        if ticker_value is None:
            ticker_disp = "—"
        elif format_type == "%":
            ticker_disp = f"{ticker_value * 100:.1f}%"
        else:  # ratio
            ticker_disp = f"{ticker_value:.2f}"

        # Format sector avg
        if sector_avg is None:
            sector_disp = "—"
        elif format_type == "%":
            sector_disp = f"{sector_avg * 100:.1f}%"
        else:
            sector_disp = f"{sector_avg:.2f}"

        # Compute delta
        if ticker_value is not None and sector_avg is not None and sector_avg != 0:
            delta_pct = (ticker_value / sector_avg - 1) * 100
            arrow = "▲" if delta_pct >= 0 else "▼"
            delta_disp = f"{arrow} {abs(round(delta_pct))}%"

            # Determine signal emoji
            if better_direction == "lower":
                # Lower is better (valuation & leverage)
                if delta_pct <= -10:
                    signal = "🟢"
                elif delta_pct >= 10:
                    signal = "🔴"
                else:
                    signal = "🟠"
            else:  # higher is better
                # Higher is better (profitability & strength)
                if delta_pct >= 10:
                    signal = "🟢"
                elif delta_pct <= -10:
                    signal = "🔴"
                else:
                    signal = "🟠"
        else:
            delta_disp = "—"
            signal = "🟠"

        metrics_rows.append({
            "metric": metric_name,
            "ticker_value": ticker_disp,
            "sector_avg": sector_disp,
            "delta": delta_disp,
            "signal": signal,
        })

    # Build growth and balance sheet metrics
    growth_rows = build_growth_metrics(detail)
    balance_rows = build_balance_sheet_metrics(detail)

    # Build additional metric cards (conditionally)
    additional_cards = []

    if growth_rows:
        additional_cards.append(
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    html.Div("Growth & Cash Flow", className="card-title"),
                    DataTable(
                        columns=[
                            {"name": "Metric", "id": "metric"},
                            {"name": "Value", "id": "value"},
                            {"name": "Signal", "id": "signal"},
                        ],
                        data=growth_rows,
                        style_table={"overflowX": "auto"},
                        style_cell={"padding": "10px", "textAlign": "left"},
                        style_header={"fontWeight": "600"},
                    ),
                ],
            )
        )

    if balance_rows:
        additional_cards.append(
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    html.Div("Balance Sheet & Solvency", className="card-title"),
                    DataTable(
                        columns=[
                            {"name": "Metric", "id": "metric"},
                            {"name": "Value", "id": "value"},
                            {"name": "Signal", "id": "signal"},
                        ],
                        data=balance_rows,
                        style_table={"overflowX": "auto"},
                        style_cell={"padding": "10px", "textAlign": "left"},
                        style_header={"fontWeight": "600"},
                    ),
                ],
            )
        )

    return html.Div(
        children=[
            # Header card
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                        children=[
                            html.Div(
                                children=[
                                    html.H3(ticker, style={"margin": "0"}),
                                    html.Div(
                                        detail.get("sector", "Unknown sector"),
                                        className="hint-text",
                                    ),
                                ],
                            ),
                            html.Div(
                                label,
                                style={
                                    "color": label_color,
                                    "fontWeight": "600",
                                    "fontSize": "16px",
                                },
                            ),
                        ],
                    ),
                ],
            ),
            # KPI cards: 1 row, 4 columns
            dbc.Row(
                [dbc.Col(card, width=3) for card in kpi_cards],
                className="g-3",
                style={"marginBottom": "14px"},
            ),
            # Additional metric cards (Growth & Balance Sheet)
            *additional_cards,
            # Metrics vs Sector table
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    html.Div("Metrics vs Sector", className="card-title"),
                    DataTable(
                        columns=[
                            {"name": "Metric", "id": "metric"},
                            {"name": "Ticker", "id": "ticker_value"},
                            {"name": "Sector Avg", "id": "sector_avg"},
                            {"name": "Δ vs Sector", "id": "delta"},
                            {"name": "Signal", "id": "signal"},
                        ],
                        data=metrics_rows,
                        style_table={"overflowX": "auto"},
                        style_cell={"padding": "10px", "textAlign": "left"},
                        style_header={"fontWeight": "600"},
                    ),
                ],
            ),
            # AI Analysis (on-demand)
            html.Div(
                className="card",
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                        children=[
                            html.Div("AI Analysis", className="card-title"),
                            html.Button(
                                "Generate Analysis",
                                id="fund-ai-generate-btn",
                                className="btn-secondary",
                                style={"fontSize": "13px", "padding": "4px 10px"},
                            ),
                        ],
                    ),
                    dcc.Loading(
                        type="dot",
                        children=html.Div(id="fund-ai-output"),
                    ),
                ],
            ),
        ],
    ), None


# Callback: trigger AI analysis on button click
@callback(
    Output("fund-ai-payload", "data", allow_duplicate=True),
    Input("fund-ai-generate-btn", "n_clicks"),
    State("fundamental-active-ticker", "data"),
    State("fundamental-benchmark", "value"),
    prevent_initial_call=True,
)
def trigger_ai_analysis(n_clicks, ticker, benchmark_id):
    if not ticker or not benchmark_id:
        raise PreventUpdate

    detail = get_ticker_snapshot_detail(benchmark_id, ticker)
    if not detail:
        raise PreventUpdate

    # Load all tickers for sector comparison
    all_tickers = get_benchmark_tickers_with_fundamentals(benchmark_id)
    ticker_sector = detail.get("sector")

    # Compute sector averages (within same benchmark + same sector)
    sector_tickers = [t for t in all_tickers if t.get("sector") == ticker_sector] if ticker_sector else []

    def compute_sector_avg(field):
        """Compute sector average for a metric field."""
        if len(sector_tickers) < 5:
            return None
        values = [t.get(field) for t in sector_tickers if t.get(field) is not None]
        return sum(values) / len(values) if values else None

    # Build metrics table (same logic as load_breakdown)
    metrics_config = [
        ("ROE", "roe", "%", "higher"),
        ("Operating Margin", "operating_margins", "%", "higher"),
        ("P/E (TTM)", "pe_ttm", "ratio", "lower"),
        ("Forward P/E", "forward_pe", "ratio", "lower"),
        ("PEG", "peg", "ratio", "lower"),
        ("EV/EBITDA", "ev_to_ebitda", "ratio", "lower"),
        ("Price/Book", "price_to_book", "ratio", "lower"),
        ("Price/Sales", "price_to_sales", "ratio", "lower"),
    ]

    metrics_rows = []
    for metric_name, field, format_type, better_direction in metrics_config:
        ticker_value = detail.get(field)
        sector_avg = compute_sector_avg(field)

        # Format ticker value
        if ticker_value is None:
            ticker_disp = "—"
        elif format_type == "%":
            ticker_disp = f"{ticker_value * 100:.1f}%"
        else:  # ratio
            ticker_disp = f"{ticker_value:.2f}"

        # Format sector avg
        if sector_avg is None:
            sector_disp = "—"
        elif format_type == "%":
            sector_disp = f"{sector_avg * 100:.1f}%"
        else:
            sector_disp = f"{sector_avg:.2f}"

        # Compute delta
        if ticker_value is not None and sector_avg is not None and sector_avg != 0:
            delta_pct = (ticker_value / sector_avg - 1) * 100
            arrow = "▲" if delta_pct >= 0 else "▼"
            delta_disp = f"{arrow} {abs(round(delta_pct))}%"

            # Determine signal emoji
            if better_direction == "lower":
                # Lower is better (valuation & leverage)
                if delta_pct <= -10:
                    signal = "🟢"
                elif delta_pct >= 10:
                    signal = "🔴"
                else:
                    signal = "🟠"
            else:  # higher is better
                # Higher is better (profitability & strength)
                if delta_pct >= 10:
                    signal = "🟢"
                elif delta_pct <= -10:
                    signal = "🔴"
                else:
                    signal = "🟠"
        else:
            delta_disp = "—"
            signal = "🟠"

        metrics_rows.append({
            "metric": metric_name,
            "ticker_value": ticker_disp,
            "sector_avg": sector_disp,
            "delta": delta_disp,
            "signal": signal,
        })

    # Build growth and balance sheet metrics
    growth_rows = build_growth_metrics(detail)
    balance_rows = build_balance_sheet_metrics(detail)

    # Prepare payload for AI
    ai_payload = {
        "ticker": ticker,
        "benchmark_id": benchmark_id,
        "sector": detail.get("sector"),
        "fundamental_label": detail.get("fundamental_label"),
        "bench_score_quality": detail.get("bench_score_quality"),
        "bench_score_safety": detail.get("bench_score_safety"),
        "bench_score_value": detail.get("bench_score_value"),
        "updated_at": detail.get("updated_at"),
        "growth_metrics": growth_rows,
        "balance_metrics": balance_rows,
        "metrics_rows": metrics_rows,
    }

    return ai_payload


# Callback: generate AI analysis (async)
@callback(
    Output("fund-ai-output", "children"),
    Input("fund-ai-payload", "data"),
)
def generate_ai_analysis(payload):
    if not payload:
        raise PreventUpdate

    ticker = payload["ticker"]
    benchmark_id = payload["benchmark_id"]
    metrics_rows = payload["metrics_rows"]
    updated_at = payload.get("updated_at", "")

    # Check cache first
    cached = get_cached_ai_analysis(ticker, updated_at)
    if cached:
        return html.Div(
            cached,
            style={"fontSize": "13px", "lineHeight": "1.35"},
        )

    # Build detail-like dict for _generate_ai_analysis
    detail = {
        "sector": payload.get("sector"),
        "fundamental_label": payload.get("fundamental_label"),
        "bench_score_quality": payload.get("bench_score_quality"),
        "bench_score_safety": payload.get("bench_score_safety"),
        "bench_score_value": payload.get("bench_score_value"),
        "growth_metrics": payload.get("growth_metrics", []),
        "balance_metrics": payload.get("balance_metrics", []),
    }

    ai_content = _generate_ai_analysis(ticker, detail, metrics_rows, benchmark_id)

    # Cache result before returning
    cache_ai_analysis(ticker, updated_at, ai_content)

    # Wrap in smaller font container
    return html.Div(
        ai_content,
        style={"fontSize": "13px", "lineHeight": "1.35"},
    )


def _generate_ai_analysis(ticker, detail, metrics_rows, benchmark_id):
    """Generate AI analysis using local AI connector if enabled."""
    try:
        # Get AI settings (use portfolio_id=1 as default for fundamental analysis)
        ai_settings = get_ai_settings(portfolio_id=1)

        if not ai_settings or not ai_settings.get("enabled"):
            return html.Div(
                "Local AI analysis unavailable.",
                className="hint-text",
            )

        # Build growth metrics text from detail (if available)
        growth_metrics = detail.get("growth_metrics", [])
        growth_text = "\n".join([
            f"- {row['metric']}: {row['value']} {row['signal']}"
            for row in growth_metrics
        ]) if growth_metrics else "Not available"

        # Build balance sheet metrics text from detail (if available)
        balance_metrics = detail.get("balance_metrics", [])
        balance_text = "\n".join([
            f"- {row['metric']}: {row['value']} {row['signal']}"
            for row in balance_metrics
        ]) if balance_metrics else "Not available"

        # Prepare metrics summary for AI
        metrics_text = "\n".join([
            f"- {row['metric']}: {row['ticker_value']} (Sector: {row['sector_avg']}, Δ: {row['delta']}, Signal: {row['signal']})"
            for row in metrics_rows
        ])

        prompt = f"""Analyze this ticker in clear, easy English (250 words max):

Ticker: {ticker}
Sector: {detail.get('sector', 'Unknown')}
Label: {detail.get('fundamental_label', 'Unknown')}

Scores:
- Durability: {round((detail.get('bench_score_quality', 0) + detail.get('bench_score_safety', 0)) / 2)}
- Quality: {round(detail.get('bench_score_quality', 0))}
- Safety: {round(detail.get('bench_score_safety', 0))}
- Value: {round(detail.get('bench_score_value', 0))}

Growth & Cash Flow:
{growth_text}

Balance Sheet & Solvency:
{balance_text}

Valuation Metrics vs Sector:
{metrics_text}

Provide:
1. **Key Takeaways** (3–5 bullets): What stands out from growth, cash flow, balance sheet, and valuation?
2. **Main Risks** (2–4 bullets): Financial health concerns (leverage, liquidity, growth sustainability)?
3. **What to Check Next** (1–3 bullets): Due diligence steps
4. **Bottom Line** (one sentence): Clear verdict on financial quality

Focus on growth sustainability, cash generation, balance sheet strength, and valuation together."""

        # Call local AI API
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
        result = response.json()
        ai_text = result.get("response", "No response from model.")

        return dcc.Markdown(ai_text)

    except Exception:
        return html.Div(
            "Local AI analysis unavailable.",
            className="hint-text",
        )


# Callback: update button states when data or page changes
@callback(
    Output("fund-pager-first", "disabled"),
    Output("fund-pager-prev", "disabled"),
    Output("fund-pager-next", "disabled"),
    Output("fund-pager-last", "disabled"),
    Input("fundamental-finder-table", "page_current"),
    Input("fundamentals-finder-store", "data"),
)
def update_pagination_button_states(current_page, store_data):
    """Update pagination button disabled states based on current page and data."""
    if not store_data:
        # No data: disable all buttons
        return True, True, True, True

    page_size = 20
    total_pages = max(1, (len(store_data) + page_size - 1) // page_size)

    # Clamp current_page to valid range
    current_page = max(0, min(current_page or 0, total_pages - 1))

    # Calculate button disabled states
    first_disabled = prev_disabled = (current_page == 0)
    next_disabled = last_disabled = (current_page >= total_pages - 1)

    return first_disabled, prev_disabled, next_disabled, last_disabled


# Callback: custom pagination (button click handlers)
@callback(
    Output("fundamental-finder-table", "page_current", allow_duplicate=True),
    Input("fund-pager-first", "n_clicks"),
    Input("fund-pager-prev", "n_clicks"),
    Input("fund-pager-next", "n_clicks"),
    Input("fund-pager-last", "n_clicks"),
    State("fundamental-finder-table", "page_current"),
    State("fundamentals-finder-store", "data"),
    prevent_initial_call=True,
)
def handle_pagination(first_clicks, prev_clicks, next_clicks, last_clicks, current_page, store_data):
    from dash import ctx

    if not ctx.triggered or not store_data:
        raise PreventUpdate

    # Determine which button was clicked
    button_id = ctx.triggered[0]["prop_id"].split(".")[0]

    # Calculate total pages
    page_size = 20
    total_pages = max(1, (len(store_data) + page_size - 1) // page_size)

    # Calculate new page index (0-based)
    if button_id == "fund-pager-first":
        new_page = 0
    elif button_id == "fund-pager-prev":
        new_page = max(0, current_page - 1)
    elif button_id == "fund-pager-next":
        new_page = min(total_pages - 1, current_page + 1)
    elif button_id == "fund-pager-last":
        new_page = total_pages - 1
    else:
        raise PreventUpdate

    return new_page


