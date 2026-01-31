from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html, Input, Output, State, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate
from datetime import datetime

from app.db.benchmarks_repo import (
    list_benchmarks,
    get_benchmark_snapshot_tickers,
    get_ticker_snapshot_detail,
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
            # Stores
            dcc.Store(id="fundamental-active-ticker", data=None),
            dcc.Store(id="fundamental-ai-job-status", data=None),

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
                                    {"name": "Total", "id": "bench_score_total", "type": "numeric", "format": {"specifier": ".1f"}},
                                    {"name": "Quality", "id": "quality_disp"},
                                    {"name": "Safety", "id": "safety_disp"},
                                    {"name": "Value", "id": "value_disp"},
                                    {"name": "Confidence", "id": "bench_confidence"},
                                    {"name": "Updated", "id": "updated_at"},
                                ],
                                data=[],
                                page_size=20,
                                sort_action="native",
                                row_selectable="single",
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                                style_data_conditional=[
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


# Callback: load finder table
@callback(
    Output("fundamental-finder-table", "data"),
    Output("fundamental-status-bar", "children"),
    Input("fundamental-benchmark", "value"),
)
def load_finder_table(benchmark_id):
    if not benchmark_id:
        return [], "Select a benchmark to load candidates."

    tickers = get_benchmark_snapshot_tickers(benchmark_id)

    if not tickers:
        return [], "No snapshot data available. Go to Market → Breakdown to refresh."

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

    # Add display strings for Quality/Safety/Value columns
    for row in tickers:
        sector = row.get("sector")
        sector_avg = sector_avgs.get(sector, {})

        for dimension in ["quality", "safety", "value"]:
            score = row.get(f"bench_score_{dimension}")
            avg = sector_avg.get(dimension)

            if score is None:
                row[f"{dimension}_disp"] = "—"
            elif avg is None or avg == 0:
                row[f"{dimension}_disp"] = f"{score:.1f} (—)"
            else:
                delta_pct = (score - avg) / avg * 100
                sign = "+" if delta_pct >= 0 else ""
                row[f"{dimension}_disp"] = f"{score:.1f} ({sign}{delta_pct:.1f}%)"

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

    return sorted_tickers, f"Loaded {len(tickers)} ticker(s) from snapshot."


# Callback: toggle panels
@callback(
    Output("fundamental-panel-finder", "style"),
    Output("fundamental-panel-breakdown", "style"),
    Output("fundamental-nav-finder", "active"),
    Output("fundamental-nav-breakdown", "active"),
    Output("fundamental-nav-finder", "style"),
    Output("fundamental-nav-breakdown", "style"),
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
        )
    elif button_id == "fundamental-nav-breakdown":
        return (
            {"display": "none"},
            {"display": "block"},
            False,
            True,
            PILL_INACTIVE_STYLE,
            PILL_ACTIVE_STYLE,
        )
    else:
        raise PreventUpdate


# Callback: row selection sets active ticker and switches to breakdown
@callback(
    Output("fundamental-active-ticker", "data"),
    Output("fundamental-panel-finder", "style", allow_duplicate=True),
    Output("fundamental-panel-breakdown", "style", allow_duplicate=True),
    Output("fundamental-nav-finder", "active", allow_duplicate=True),
    Output("fundamental-nav-breakdown", "active", allow_duplicate=True),
    Output("fundamental-nav-finder", "style", allow_duplicate=True),
    Output("fundamental-nav-breakdown", "style", allow_duplicate=True),
    Input("fundamental-finder-table", "selected_rows"),
    State("fundamental-finder-table", "data"),
    prevent_initial_call=True,
)
def select_ticker(selected_rows, data):
    if not selected_rows or not data:
        raise PreventUpdate

    row_idx = selected_rows[0]
    ticker = data[row_idx]["ticker"]

    return (
        ticker,
        {"display": "none"},
        {"display": "block"},
        False,
        True,
        PILL_INACTIVE_STYLE,
        PILL_ACTIVE_STYLE,
    )


# Callback: load breakdown content
@callback(
    Output("fundamental-breakdown-content", "children"),
    Input("fundamental-active-ticker", "data"),
    State("fundamental-benchmark", "value"),
)
def load_breakdown(ticker, benchmark_id):
    if not ticker or not benchmark_id:
        return html.Div(
            className="card",
            children=[
                html.Div("No Ticker Selected", className="card-title"),
                html.P("Select a ticker from Finder to view details."),
            ],
        )

    detail = get_ticker_snapshot_detail(benchmark_id, ticker)

    if not detail:
        return html.Div(
            className="card",
            children=[
                html.Div(f"{ticker}", className="card-title"),
                html.P("No snapshot data available for this ticker."),
            ],
        )

    # Header with label badge
    label = detail.get("fundamental_label", "unknown")
    label_color = {
        "INTERESTING": "var(--ok)",
        "EXPENSIVE": "var(--warning)",
        "DOUBTFUL": "var(--text-muted)",
        "AVOID": "var(--danger)",
    }.get(label, "var(--text)")

    # Score cards
    score_cards = []
    if detail.get("bench_score_total") is not None:
        score_cards.append(
            html.Div(
                className="card",
                style={"textAlign": "center"},
                children=[
                    html.Div("Total Score", className="hint-text", style={"marginBottom": "5px"}),
                    html.Div(f"{detail['bench_score_total']:.1f}", style={"fontSize": "24px", "fontWeight": "600"}),
                ],
            )
        )

    if detail.get("bench_score_quality") is not None:
        score_cards.append(
            html.Div(
                className="card",
                style={"textAlign": "center"},
                children=[
                    html.Div("Quality", className="hint-text", style={"marginBottom": "5px"}),
                    html.Div(f"{detail['bench_score_quality']:.1f}", style={"fontSize": "24px", "fontWeight": "600"}),
                ],
            )
        )

    if detail.get("bench_score_safety") is not None:
        score_cards.append(
            html.Div(
                className="card",
                style={"textAlign": "center"},
                children=[
                    html.Div("Safety", className="hint-text", style={"marginBottom": "5px"}),
                    html.Div(f"{detail['bench_score_safety']:.1f}", style={"fontSize": "24px", "fontWeight": "600"}),
                ],
            )
        )

    if detail.get("bench_score_value") is not None:
        score_cards.append(
            html.Div(
                className="card",
                style={"textAlign": "center"},
                children=[
                    html.Div("Value", className="hint-text", style={"marginBottom": "5px"}),
                    html.Div(f"{detail['bench_score_value']:.1f}", style={"fontSize": "24px", "fontWeight": "600"}),
                ],
            )
        )

    # Essentials table
    essentials = []
    if detail.get("sector"):
        essentials.append({"metric": "Sector", "value": detail["sector"]})
    if detail.get("bench_sector_pct_total") is not None:
        essentials.append({"metric": "Sector Percentile", "value": f"{detail['bench_sector_pct_total']:.1f}"})
    if detail.get("bench_confidence"):
        essentials.append({"metric": "Confidence", "value": detail["bench_confidence"]})
    if detail.get("updated_at"):
        essentials.append({"metric": "Updated", "value": detail["updated_at"]})

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
            # Score cards grid
            html.Div(
                className="grid-4" if len(score_cards) == 4 else "grid-3",
                style={"marginBottom": "14px"},
                children=score_cards,
            ) if score_cards else html.Div(),
            # Essentials table
            html.Div(
                className="card",
                style={"marginBottom": "14px"},
                children=[
                    html.Div("Essentials", className="card-title"),
                    DataTable(
                        columns=[
                            {"name": "Metric", "id": "metric"},
                            {"name": "Value", "id": "value"},
                        ],
                        data=essentials,
                        style_table={"overflowX": "auto"},
                        style_cell={"padding": "10px", "textAlign": "left"},
                        style_header={"fontWeight": "600"},
                    ),
                ],
            ),
            # AI Evaluation card
            html.Div(
                className="card",
                children=[
                    html.Div("AI Evaluation", className="card-title"),
                    html.Div(
                        style={"marginBottom": "10px"},
                        children=[
                            html.Div("Mode", className="field-label"),
                            dcc.RadioItems(
                                id="fundamental-ai-mode",
                                options=[
                                    {"label": "Brief", "value": "brief"},
                                    {"label": "Deep", "value": "deep"},
                                ],
                                value="brief",
                                inline=True,
                            ),
                        ],
                    ),
                    html.Button(
                        "Generate AI note",
                        id="fundamental-ai-generate-btn",
                        className="btn-primary",
                        n_clicks=0,
                    ),
                    html.Div(
                        id="fundamental-ai-output",
                        style={"marginTop": "10px"},
                    ),
                ],
            ),
        ],
    )


# Callback: AI note generation
@callback(
    Output("fundamental-ai-output", "children"),
    Output("fundamental-ai-job-status", "data"),
    Input("fundamental-ai-generate-btn", "n_clicks"),
    State("fundamental-active-ticker", "data"),
    State("fundamental-benchmark", "value"),
    State("fundamental-ai-mode", "value"),
    prevent_initial_call=True,
)
def generate_ai_note(n_clicks, ticker, benchmark_id, mode):
    if n_clicks == 0 or not ticker or not benchmark_id:
        raise PreventUpdate

    # Simplified: generate immediately (no background job for Phase 3 MVP)
    # In production, this would use async/background processing

    detail = get_ticker_snapshot_detail(benchmark_id, ticker)

    if not detail:
        return html.Div("No data available for AI evaluation.", style={"color": "var(--danger)"}), None

    # Simple AI note generation (placeholder - in production use actual LLM)
    if mode == "brief":
        note = f"""**{ticker}** ({detail.get('sector', 'Unknown')})

**Label:** {detail.get('fundamental_label', 'N/A')}
**Score:** {detail.get('bench_score_total', 0):.1f}/100

Brief assessment based on stored fundamentals. This ticker shows {'strong' if detail.get('bench_score_total', 0) > 70 else 'moderate' if detail.get('bench_score_total', 0) > 50 else 'weak'} fundamental indicators.

**Next steps:** Review detailed financials, check recent news, verify sector trends.

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
    else:
        note = f"""**{ticker}** Deep Fundamental Analysis

**Sector:** {detail.get('sector', 'Unknown')}
**Label:** {detail.get('fundamental_label', 'N/A')}

**Scores:**
- Total: {detail.get('bench_score_total', 0):.1f}/100
- Quality: {detail.get('bench_score_quality', 0):.1f}/100
- Safety: {detail.get('bench_score_safety', 0):.1f}/100
- Value: {detail.get('bench_score_value', 0):.1f}/100

**Sector Position:** {detail.get('bench_sector_pct_total', 0):.1f}th percentile within {detail.get('sector', 'sector')}

**Confidence:** {detail.get('bench_confidence', 'N/A')}

**Key Considerations:**
- Fundamental quality indicators based on ROE, margins
- Safety metrics including leverage and valuation ratios
- Value assessment through P/E, PEG, and price multiples

**Macro Context:** Consider current interest rate environment, sector-specific regulatory changes, and geopolitical risks (tariffs, trade policy shifts).

**Verification Steps:**
1. Review latest earnings reports
2. Check for recent management changes
3. Analyze peer comparison within sector
4. Assess macro headwinds/tailwinds

*Note: This is a data-driven assessment, not financial advice. Always verify independently.*

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

    return dcc.Markdown(note), {"ticker": ticker, "mode": mode, "timestamp": datetime.now().isoformat()}
