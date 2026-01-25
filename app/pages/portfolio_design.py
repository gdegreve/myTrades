from __future__ import annotations
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from dash import dcc, html, Input, Output, State, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate

from app.db.portfolio_repo import list_portfolios
from app.db.policy_repo import load_policy_snapshot, save_policy_snapshot

# Debug toggle: set to False to hide debug panel
DEBUG_DESIGN_PAGE = True


def layout() -> html.Div:
    return html.Div(
        children=[
            # Stores for edit state management (Phase 3)
            dcc.Store(id="design-edit-state"),
            dcc.Store(id="design-saved-snapshot"),

            html.Div(
                className="page-header",
                children=[
                    html.Div(
                        children=[
                            html.H2("Portfolio – Design (Requirements)", style={"margin": "0"}),
                            html.Div(
                                "Define targets, limits and rebalancing rules for this portfolio.",
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
                                        id="design-portfolio",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        style={"minWidth": "220px"},
                                    ),
                                ]
                            ),
                            html.Button(
                                "Save policy",
                                id="design-save",
                                className="btn-primary",
                                disabled=True,
                                n_clicks=0,
                            ),
                        ],
                    ),
                ],
            ),

            # Status bar
            html.Div(
                id="design-status-bar",
                className="status-bar",
                children="Select a portfolio to view policy",
            ),

            # Pie charts row
            html.Div(
                className="grid-2",
                style={"marginTop": "14px", "marginBottom": "14px"},
                children=[
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Target Allocation – Sectors", className="card-title"),
                            html.Div(id="design-sector-total", className="hint-text", style={"marginBottom": "8px"}),
                            dcc.Graph(id="design-sector-chart", config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        className="card",
                        children=[
                            html.Div("Target Allocation – Regions", className="card-title"),
                            html.Div(id="design-region-total", className="hint-text", style={"marginBottom": "8px"}),
                            dcc.Graph(id="design-region-chart", config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),

            # Accordion with editable tables and policy settings
            dbc.Accordion(
                id="design-accordion",
                start_collapsed=False,
                children=[
                    dbc.AccordionItem(
                        title="Sector Allocation",
                        children=[
                            html.Div(
                                "Editable table. Fill the bottom row to add new sectors. Select rows and click Delete to remove.",
                                className="hint-text",
                                style={"marginBottom": "10px"},
                            ),
                            dbc.Button(
                                "Delete selected",
                                id="design-sector-delete",
                                color="secondary",
                                size="sm",
                                style={"marginBottom": "10px"},
                                n_clicks=0,
                            ),
                            DataTable(
                                id="design-sector-targets",
                                columns=[
                                    {"name": "Sector", "id": "sector", "editable": True},
                                    {"name": "Target %", "id": "target_pct", "type": "numeric", "editable": True},
                                    {"name": "Min %", "id": "min_pct", "type": "numeric", "editable": True},
                                    {"name": "Max %", "id": "max_pct", "type": "numeric", "editable": True},
                                ],
                                data=[],
                                page_size=12,
                                row_selectable="multi",
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),
                    dbc.AccordionItem(
                        title="Region Allocation",
                        children=[
                            html.Div(
                                "Editable table. Fill the bottom row to add new regions. Select rows and click Delete to remove.",
                                className="hint-text",
                                style={"marginBottom": "10px"},
                            ),
                            dbc.Button(
                                "Delete selected",
                                id="design-region-delete",
                                color="secondary",
                                size="sm",
                                style={"marginBottom": "10px"},
                                n_clicks=0,
                            ),
                            DataTable(
                                id="design-region-targets",
                                columns=[
                                    {"name": "Region", "id": "region", "editable": True},
                                    {"name": "Target %", "id": "target_pct", "type": "numeric", "editable": True},
                                    {"name": "Min %", "id": "min_pct", "type": "numeric", "editable": True},
                                    {"name": "Max %", "id": "max_pct", "type": "numeric", "editable": True},
                                ],
                                data=[],
                                page_size=12,
                                row_selectable="multi",
                                style_table={"overflowX": "auto"},
                                style_cell={"padding": "10px", "textAlign": "left"},
                                style_header={"fontWeight": "600"},
                            ),
                        ],
                    ),
                    dbc.AccordionItem(
                        title="Policy Settings",
                        children=[
                            html.Div(
                                className="card",
                                style={"border": "none", "padding": "0"},
                                children=[
                                    html.Div("Benchmark & Profile", className="card-title"),
                                    html.Div(
                                        className="grid-3",
                                        children=[
                                            html.Div(
                                                children=[
                                                    html.Div("Benchmark", className="field-label"),
                                                    dbc.Select(
                                                        id="design-benchmark",
                                                        options=[
                                                            {"label": "VWCE (All-World)", "value": "VWCE"},
                                                            {"label": "S&P 500 (SPY)", "value": "SPY"},
                                                            {"label": "STOXX Europe 600", "value": "SXXP"},
                                                        ],
                                                        value=None,
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                children=[
                                                    html.Div("Risk profile", className="field-label"),
                                                    dbc.Select(
                                                        id="design-risk-profile",
                                                        options=[
                                                            {"label": "Conservative", "value": "conservative"},
                                                            {"label": "Balanced", "value": "balanced"},
                                                            {"label": "Aggressive", "value": "aggressive"},
                                                        ],
                                                        value=None,
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                children=[
                                                    html.Div("Base currency", className="field-label"),
                                                    dcc.Input(
                                                        id="design-currency",
                                                        type="text",
                                                        value="EUR",
                                                        disabled=True,
                                                        className="text-input",
                                                    ),
                                                ]
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                className="grid-2",
                                style={"marginTop": "14px"},
                                children=[
                                    html.Div(
                                        className="card",
                                        style={"border": "none", "padding": "0"},
                                        children=[
                                            html.Div("Risk limits", className="card-title"),
                                            html.Div(
                                                className="grid-2",
                                                children=[
                                                    html.Div(
                                                        children=[
                                                            html.Div("Max position size %", className="field-label"),
                                                            dcc.Input(
                                                                id="design-max-position",
                                                                type="number",
                                                                value=None,
                                                                min=0,
                                                                max=100,
                                                                step=0.5,
                                                                className="text-input",
                                                            ),
                                                        ]
                                                    ),
                                                    html.Div(
                                                        children=[
                                                            html.Div("Max sector exposure %", className="field-label"),
                                                            dcc.Input(
                                                                id="design-max-sector",
                                                                type="number",
                                                                value=None,
                                                                min=0,
                                                                max=100,
                                                                step=0.5,
                                                                className="text-input",
                                                            ),
                                                        ]
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="card",
                                        style={"border": "none", "padding": "0"},
                                        children=[
                                            html.Div("Cash policy", className="card-title"),
                                            html.Div(
                                                className="grid-3",
                                                children=[
                                                    html.Div(
                                                        children=[
                                                            html.Div("Cash min %", className="field-label"),
                                                            dcc.Input(
                                                                id="design-cash-min",
                                                                type="number",
                                                                value=None,
                                                                min=0,
                                                                max=100,
                                                                step=0.5,
                                                                className="text-input",
                                                            ),
                                                        ]
                                                    ),
                                                    html.Div(
                                                        children=[
                                                            html.Div("Cash target %", className="field-label"),
                                                            dcc.Input(
                                                                id="design-cash-target",
                                                                type="number",
                                                                value=None,
                                                                min=0,
                                                                max=100,
                                                                step=0.5,
                                                                className="text-input",
                                                            ),
                                                        ]
                                                    ),
                                                    html.Div(
                                                        children=[
                                                            html.Div("Cash max %", className="field-label"),
                                                            dcc.Input(
                                                                id="design-cash-max",
                                                                type="number",
                                                                value=None,
                                                                min=0,
                                                                max=100,
                                                                step=0.5,
                                                                className="text-input",
                                                            ),
                                                        ]
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(
                                className="card",
                                style={"marginTop": "14px", "border": "none", "padding": "0"},
                                children=[
                                    html.Div("Rebalancing policy", className="card-title"),
                                    html.Div(
                                        className="grid-3",
                                        children=[
                                            html.Div(
                                                children=[
                                                    html.Div("Frequency", className="field-label"),
                                                    dbc.Select(
                                                        id="design-rebalance-freq",
                                                        options=[
                                                            {"label": "Monthly", "value": "monthly"},
                                                            {"label": "Quarterly", "value": "quarterly"},
                                                            {"label": "Semi-annually", "value": "semiannual"},
                                                            {"label": "Annually", "value": "annual"},
                                                        ],
                                                        value=None,
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                children=[
                                                    html.Div("Drift trigger %", className="field-label"),
                                                    dcc.Input(
                                                        id="design-drift-trigger",
                                                        type="number",
                                                        value=None,
                                                        min=0,
                                                        max=100,
                                                        step=0.5,
                                                        className="text-input",
                                                    ),
                                                ]
                                            ),
                                            html.Div(
                                                children=[
                                                    html.Div("Method", className="field-label"),
                                                    dbc.Select(
                                                        id="design-rebalance-method",
                                                        options=[
                                                            {"label": "Contributions-first (preferred)", "value": "contributions_first"},
                                                            {"label": "Sell & buy to target", "value": "sell_buy"},
                                                        ],
                                                        value=None,
                                                    ),
                                                ]
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Debug panel (toggle with DEBUG_DESIGN_PAGE constant)
            html.Div(
                id="design-debug-panel",
                className="debug-panel",
                style={"display": "block" if DEBUG_DESIGN_PAGE else "none", "marginTop": "14px"},
                children=[
                    html.Div("Debug Panel", className="card-title"),
                    html.Div(id="design-debug-validation", style={"marginBottom": "6px"}),
                    html.Div(id="design-debug-totals", style={"marginBottom": "6px"}),
                    html.Div(id="design-debug-errors", style={"fontSize": "12px", "color": "#dc2626"}),
                ],
            ) if DEBUG_DESIGN_PAGE else None,
        ],
        style={"maxWidth": "1100px"},
    )


# Callback 1: populate portfolio dropdown ONLY (no status output -> avoids duplicate outputs)
@callback(
    Output("design-portfolio", "options"),
    Output("design-portfolio", "value"),
    Input("url", "pathname"),
)
def design_load_portfolios(pathname: str):
    if pathname != "/portfolio/design":
        raise PreventUpdate

    rows = list_portfolios()
    options = [{"label": r["name"], "value": r["id"]} for r in rows]
    default_value = options[0]["value"] if options else None
    return options, default_value


# Callback 2: load policy + targets for selected portfolio (single source of truth for design-status-bar)
@callback(
    Output("design-benchmark", "value"),
    Output("design-risk-profile", "value"),
    Output("design-max-position", "value"),
    Output("design-max-sector", "value"),
    Output("design-cash-min", "value"),
    Output("design-cash-target", "value"),
    Output("design-cash-max", "value"),
    Output("design-rebalance-freq", "value"),
    Output("design-drift-trigger", "value"),
    Output("design-rebalance-method", "value"),
    Output("design-sector-targets", "data"),
    Output("design-region-targets", "data"),
    Output("design-currency", "value"),
    Output("design-status-bar", "children"),
    Output("design-sector-chart", "figure"),
    Output("design-sector-total", "children"),
    Output("design-region-chart", "figure"),
    Output("design-region-total", "children"),
    Input("design-portfolio", "value"),
)
def design_load_policy(portfolio_id: int | None):
    if portfolio_id is None:
        raise PreventUpdate

    snapshot = load_policy_snapshot(int(portfolio_id))

    policy = snapshot.get("policy", {}) or {}
    sector_targets = snapshot.get("sector_targets", []) or []
    region_targets = snapshot.get("region_targets", []) or []

    # Add blank row for editing
    sector_targets = _ensure_one_blank_row(sector_targets, "sector")
    region_targets = _ensure_one_blank_row(region_targets, "region")

    # Generate sector pie chart (filter blank rows for display)
    cash_target = policy.get("cash_target_pct", 0.0) or 0.0
    expected_total = 100.0 - cash_target if cash_target and 0 <= cash_target <= 100 else 100.0

    sector_targets_for_chart = _filter_blank_rows(sector_targets, "sector")
    region_targets_for_chart = _filter_blank_rows(region_targets, "region")

    sector_fig = _create_pie_chart_with_fallback(sector_targets_for_chart, "sector", expected_total)
    sector_total = _calculate_total(sector_targets_for_chart)

    # Generate region pie chart
    region_fig = _create_pie_chart_with_fallback(region_targets_for_chart, "region", expected_total)
    region_total = _calculate_total(region_targets_for_chart)

    return (
        policy.get("benchmark_ticker", "VWCE"),
        policy.get("risk_profile", "balanced"),
        policy.get("max_position_pct", 10.0),
        policy.get("max_sector_pct", 30.0),
        policy.get("cash_min_pct", 5.0),
        policy.get("cash_target_pct", 10.0),
        policy.get("cash_max_pct", 20.0),
        policy.get("rebalance_freq", "quarterly"),
        policy.get("drift_trigger_pct", 5.0),
        policy.get("rebalance_method", "contributions_first"),
        sector_targets,
        region_targets,
        snapshot.get("base_currency", "EUR"),
        f"Loaded policy for portfolio_id={portfolio_id}",
        sector_fig,
        f"Total: {sector_total:.1f}%",
        region_fig,
        f"Total: {region_total:.1f}%",
    )


def _create_pie_chart(targets: list[dict], label_key: str) -> go.Figure:
    """Create a pie chart from allocation targets (backward compatibility - no fallback)."""
    if not targets:
        fig = go.Figure()
        fig.add_annotation(
            text="No allocation data",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color="#6b7280"),
        )
        fig.update_layout(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            margin=dict(l=0, r=0, t=0, b=0),
            height=250,
        )
        return fig

    # Filter targets with valid target_pct
    valid_targets = [t for t in targets if t.get("target_pct") is not None and t.get("target_pct") > 0]

    if not valid_targets:
        fig = go.Figure()
        fig.add_annotation(
            text="No allocation data",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color="#6b7280"),
        )
        fig.update_layout(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            margin=dict(l=0, r=0, t=0, b=0),
            height=250,
        )
        return fig

    labels = [t.get(label_key, "Unknown") for t in valid_targets]
    values = [t.get("target_pct", 0) for t in valid_targets]

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.4,
                marker=dict(
                    colors=[
                        "#0ea5a5",
                        "#38bdf8",
                        "#fb923c",
                        "#a78bfa",
                        "#fb7185",
                        "#4ade80",
                        "#fbbf24",
                        "#c084fc",
                        "#f472b6",
                        "#34d399",
                    ]
                ),
            )
        ]
    )

    fig.update_layout(
        showlegend=True,
        margin=dict(l=20, r=20, t=20, b=20),
        height=250,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", size=12),
    )

    return fig


def _create_pie_chart_with_fallback(targets: list[dict], label_key: str, expected_total: float = 100.0) -> go.Figure:
    """Create a pie chart with fallback slices for under/over allocation.

    Args:
        targets: List of allocation targets
        label_key: Key to use for labels (e.g., 'sector', 'region')
        expected_total: Expected total percentage (default 100%, may be adjusted for cash)

    Returns:
        Plotly Figure with pie chart
    """
    # Filter targets with valid target_pct
    valid_targets = [t for t in targets if t.get("target_pct") is not None and t.get("target_pct") > 0]

    labels = []
    values = []

    if valid_targets:
        labels = [t.get(label_key, "Unknown") for t in valid_targets]
        values = [t.get("target_pct", 0) for t in valid_targets]

    actual_total = sum(values)

    # Add fallback slice if needed
    diff = expected_total - actual_total
    if abs(diff) > 0.01:  # tolerance for floating point
        if diff > 0:
            labels.append(f"Unallocated {diff:.1f}%")
            values.append(diff)
        else:
            labels.append(f"Overallocated {abs(diff):.1f}%")
            values.append(abs(diff))

    # Handle empty chart
    if not labels:
        fig = go.Figure()
        fig.add_annotation(
            text="No allocation data",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color="#6b7280"),
        )
        fig.update_layout(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            margin=dict(l=0, r=0, t=0, b=0),
            height=250,
        )
        return fig

    # Create pie chart
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.4,
                marker=dict(
                    colors=[
                        "#0ea5a5",
                        "#38bdf8",
                        "#fb923c",
                        "#a78bfa",
                        "#fb7185",
                        "#4ade80",
                        "#fbbf24",
                        "#c084fc",
                        "#f472b6",
                        "#34d399",
                        "#9ca3af",  # gray for unallocated
                        "#ef4444",  # red for overallocated
                    ]
                ),
            )
        ]
    )

    fig.update_layout(
        showlegend=True,
        margin=dict(l=20, r=20, t=20, b=20),
        height=250,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", size=12),
    )

    return fig


def _calculate_total(targets: list[dict]) -> float:
    """Calculate total percentage from targets."""
    return sum(t.get("target_pct", 0) or 0 for t in targets)


def _normalize_value(val) -> float | None:
    """Normalize a value to float or None. Treats empty strings and whitespace as None."""
    if val is None:
        return None
    if isinstance(val, str):
        val = val.strip()
        if val == "":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _is_blank_row(row: dict, name_key: str) -> bool:
    """Check if a row is completely blank (name empty AND all numeric fields empty/None)."""
    name = row.get(name_key)
    target = _normalize_value(row.get("target_pct"))
    min_pct = _normalize_value(row.get("min_pct"))
    max_pct = _normalize_value(row.get("max_pct"))

    # Blank if name is empty/None AND all numeric fields are empty/None
    name_blank = not name or str(name).strip() == ""
    numeric_blank = target is None and min_pct is None and max_pct is None

    return name_blank and numeric_blank


def _ensure_one_blank_row(data: list[dict], name_key: str) -> list[dict]:
    """Ensure exactly one blank row at the bottom. Remove any other blank rows."""
    # Filter out all blank rows
    non_blank = [r for r in data if not _is_blank_row(r, name_key)]
    # Add exactly one blank row at the end
    non_blank.append({name_key: "", "target_pct": None, "min_pct": None, "max_pct": None})
    return non_blank


def _filter_blank_rows(data: list[dict], name_key: str) -> list[dict]:
    """Remove all blank rows (for validation, totals, and saving)."""
    return [r for r in data if not _is_blank_row(r, name_key)]


# Callback 3a: manage sector targets table (blank row + edits)
@callback(
    Output("design-sector-targets", "data", allow_duplicate=True),
    Input("design-sector-targets", "data"),
    prevent_initial_call=True,
)
def design_manage_sector_targets(data: list[dict] | None):
    """Ensure exactly one blank row at the bottom of sector targets."""
    if data is None:
        data = []
    return _ensure_one_blank_row(data, "sector")


# Callback 3b: manage region targets table (blank row + edits)
@callback(
    Output("design-region-targets", "data", allow_duplicate=True),
    Input("design-region-targets", "data"),
    prevent_initial_call=True,
)
def design_manage_region_targets(data: list[dict] | None):
    """Ensure exactly one blank row at the bottom of region targets."""
    if data is None:
        data = []
    return _ensure_one_blank_row(data, "region")


# Callback 3c: delete selected sector rows
@callback(
    Output("design-sector-targets", "data", allow_duplicate=True),
    Input("design-sector-delete", "n_clicks"),
    State("design-sector-targets", "data"),
    State("design-sector-targets", "selected_rows"),
    prevent_initial_call=True,
)
def design_delete_sector_rows(n_clicks: int, data: list[dict] | None, selected_rows: list[int] | None):
    """Delete selected sector rows, preserve blank row."""
    if n_clicks == 0 or data is None or selected_rows is None or len(selected_rows) == 0:
        raise PreventUpdate

    # Remove selected rows
    data = [r for i, r in enumerate(data) if i not in selected_rows]
    # Ensure one blank row
    return _ensure_one_blank_row(data, "sector")


# Callback 3d: delete selected region rows
@callback(
    Output("design-region-targets", "data", allow_duplicate=True),
    Input("design-region-delete", "n_clicks"),
    State("design-region-targets", "data"),
    State("design-region-targets", "selected_rows"),
    prevent_initial_call=True,
)
def design_delete_region_rows(n_clicks: int, data: list[dict] | None, selected_rows: list[int] | None):
    """Delete selected region rows, preserve blank row."""
    if n_clicks == 0 or data is None or selected_rows is None or len(selected_rows) == 0:
        raise PreventUpdate

    # Remove selected rows
    data = [r for i, r in enumerate(data) if i not in selected_rows]
    # Ensure one blank row
    return _ensure_one_blank_row(data, "region")


def _validate_policy_data(
    portfolio_id: int | None,
    cash_min: float | None,
    cash_target: float | None,
    cash_max: float | None,
    sector_targets: list[dict] | None,
    region_targets: list[dict] | None,
) -> tuple[str, list[str]]:
    """Validate policy data and return (status, errors).

    Returns:
        status: "OK", "WARNING", or "ERROR"
        errors: List of error/warning messages
    """
    errors = []

    if portfolio_id is None:
        return ("ERROR", ["No portfolio selected"])

    # Normalize cash values
    cash_min = _normalize_value(cash_min)
    cash_target = _normalize_value(cash_target)
    cash_max = _normalize_value(cash_max)

    # Check cash range consistency
    if cash_min is not None and cash_target is not None and cash_min > cash_target:
        errors.append("Cash: min > target")
    if cash_target is not None and cash_max is not None and cash_target > cash_max:
        errors.append("Cash: target > max")
    if cash_min is not None and cash_max is not None and cash_min > cash_max:
        errors.append("Cash: min > max")

    # Check cash percentages in [0, 100]
    for val, name in [(cash_min, "cash_min"), (cash_target, "cash_target"), (cash_max, "cash_max")]:
        if val is not None and (val < 0 or val > 100):
            errors.append(f"Cash {name} out of [0, 100]")

    # Filter out blank rows before validation
    sector_targets = _filter_blank_rows(sector_targets or [], "sector")
    region_targets = _filter_blank_rows(region_targets or [], "region")

    # Check sector targets consistency (min <= target <= max)
    for idx, row in enumerate(sector_targets):
        target = _normalize_value(row.get("target_pct"))
        min_pct = _normalize_value(row.get("min_pct"))
        max_pct = _normalize_value(row.get("max_pct"))

        # Skip rows with all None (no validation needed)
        if target is None and min_pct is None and max_pct is None:
            continue

        # Check percentages in [0, 100]
        for val, field in [(target, "target"), (min_pct, "min"), (max_pct, "max")]:
            if val is not None and (val < 0 or val > 100):
                errors.append(f"Sector row {idx + 1}: {field} out of [0, 100]")

        # Check ordering: min <= target <= max
        if min_pct is not None and target is not None and min_pct > target:
            errors.append(f"Sector row {idx + 1}: min > target")
        if target is not None and max_pct is not None and target > max_pct:
            errors.append(f"Sector row {idx + 1}: target > max")
        if min_pct is not None and max_pct is not None and min_pct > max_pct:
            errors.append(f"Sector row {idx + 1}: min > max")

    # Check region targets consistency (min <= target <= max)
    for idx, row in enumerate(region_targets):
        target = _normalize_value(row.get("target_pct"))
        min_pct = _normalize_value(row.get("min_pct"))
        max_pct = _normalize_value(row.get("max_pct"))

        # Skip rows with all None (no validation needed)
        if target is None and min_pct is None and max_pct is None:
            continue

        # Check percentages in [0, 100]
        for val, field in [(target, "target"), (min_pct, "min"), (max_pct, "max")]:
            if val is not None and (val < 0 or val > 100):
                errors.append(f"Region row {idx + 1}: {field} out of [0, 100]")

        # Check ordering: min <= target <= max
        if min_pct is not None and target is not None and min_pct > target:
            errors.append(f"Region row {idx + 1}: min > target")
        if target is not None and max_pct is not None and target > max_pct:
            errors.append(f"Region row {idx + 1}: target > max")
        if min_pct is not None and max_pct is not None and min_pct > max_pct:
            errors.append(f"Region row {idx + 1}: min > max")

    # Check totals (WARNING only if mismatch)
    sector_total = sum(_normalize_value(r.get("target_pct")) or 0 for r in sector_targets)
    region_total = sum(_normalize_value(r.get("target_pct")) or 0 for r in region_targets)

    expected_total = 100.0
    if cash_target is not None and 0 <= cash_target <= 100:
        expected_total = 100.0 - cash_target

    if abs(sector_total - expected_total) > 0.1:
        errors.append(f"WARNING: Sector total {sector_total:.1f}% != expected {expected_total:.1f}%")
    if abs(region_total - expected_total) > 0.1:
        errors.append(f"WARNING: Region total {region_total:.1f}% != expected {expected_total:.1f}%")

    if not errors:
        return ("OK", [])

    # Determine if any errors are blocking (non-WARNING)
    blocking_errors = [e for e in errors if not e.startswith("WARNING:")]
    if blocking_errors:
        return ("ERROR", errors)
    else:
        return ("WARNING", errors)


# Callback 3: validate form and enable/disable save button
@callback(
    Output("design-save", "disabled"),
    Input("design-portfolio", "value"),
    Input("design-cash-min", "value"),
    Input("design-cash-target", "value"),
    Input("design-cash-max", "value"),
    Input("design-sector-targets", "data"),
    Input("design-region-targets", "data"),
)
def design_validate_form(
    portfolio_id: int | None,
    cash_min: float | None,
    cash_target: float | None,
    cash_max: float | None,
    sector_targets: list[dict] | None,
    region_targets: list[dict] | None,
):
    """Enable save button only if portfolio selected and basic validation passes."""
    status, errors = _validate_policy_data(
        portfolio_id, cash_min, cash_target, cash_max, sector_targets, region_targets
    )

    # Disable save if ERROR (but allow if WARNING or OK)
    return status == "ERROR"


# Callback 3e: live update charts when allocation tables change
@callback(
    Output("design-sector-chart", "figure", allow_duplicate=True),
    Output("design-sector-total", "children", allow_duplicate=True),
    Output("design-region-chart", "figure", allow_duplicate=True),
    Output("design-region-total", "children", allow_duplicate=True),
    Input("design-sector-targets", "data"),
    Input("design-region-targets", "data"),
    State("design-cash-target", "value"),
    prevent_initial_call=True,
)
def design_update_charts_live(
    sector_data: list[dict] | None,
    region_data: list[dict] | None,
    cash_target: float | None,
):
    """Update pie charts live when allocation tables change."""
    # Filter out blank rows for chart rendering
    # Note: Expected total calculation - prefer 100% - cash_target if cash_target is set,
    # otherwise expect 100%. This ensures charts, status bar, and save gating are consistent.
    expected_total = 100.0
    if cash_target is not None and 0 <= cash_target <= 100:
        expected_total = 100.0 - cash_target

    sector_targets = _filter_blank_rows(sector_data or [], "sector")
    region_targets = _filter_blank_rows(region_data or [], "region")

    sector_fig = _create_pie_chart_with_fallback(sector_targets, "sector", expected_total)
    sector_total = _calculate_total(sector_targets)

    region_fig = _create_pie_chart_with_fallback(region_targets, "region", expected_total)
    region_total = _calculate_total(region_targets)

    return (
        sector_fig,
        f"Total: {sector_total:.1f}%",
        region_fig,
        f"Total: {region_total:.1f}%",
    )


# Callback 3f: debug panel (only active if DEBUG_DESIGN_PAGE = True)
if DEBUG_DESIGN_PAGE:
    @callback(
        Output("design-debug-validation", "children"),
        Output("design-debug-totals", "children"),
        Output("design-debug-errors", "children"),
        Input("design-portfolio", "value"),
        Input("design-cash-min", "value"),
        Input("design-cash-target", "value"),
        Input("design-cash-max", "value"),
        Input("design-sector-targets", "data"),
        Input("design-region-targets", "data"),
    )
    def design_debug_update(
        portfolio_id: int | None,
        cash_min: float | None,
        cash_target: float | None,
        cash_max: float | None,
        sector_targets: list[dict] | None,
        region_targets: list[dict] | None,
    ):
        """Update debug panel with validation state and computed totals."""
        status, errors = _validate_policy_data(
            portfolio_id, cash_min, cash_target, cash_max, sector_targets, region_targets
        )

        # Compute totals
        sector_targets_filtered = _filter_blank_rows(sector_targets or [], "sector")
        region_targets_filtered = _filter_blank_rows(region_targets or [], "region")

        sector_total = sum(_normalize_value(r.get("target_pct")) or 0 for r in sector_targets_filtered)
        region_total = sum(_normalize_value(r.get("target_pct")) or 0 for r in region_targets_filtered)

        cash_target_norm = _normalize_value(cash_target)
        expected_total = 100.0
        if cash_target_norm is not None and 0 <= cash_target_norm <= 100:
            expected_total = 100.0 - cash_target_norm

        # Build status string
        status_color = {"OK": "#10b981", "WARNING": "#f59e0b", "ERROR": "#dc2626"}.get(status, "#6b7280")
        validation_text = html.Span(
            [
                "Validation status: ",
                html.Span(status, style={"fontWeight": "600", "color": status_color}),
            ]
        )

        totals_text = (
            f"Sector total: {sector_total:.1f}% | "
            f"Region total: {region_total:.1f}% | "
            f"Expected: {expected_total:.1f}%"
        )

        errors_text = "; ".join(errors) if errors else "No errors"

        return validation_text, totals_text, errors_text


# Callback 4: save policy + sector targets + region targets
@callback(
    Output("design-status-bar", "children", allow_duplicate=True),
    Input("design-save", "n_clicks"),
    State("design-portfolio", "value"),
    State("design-benchmark", "value"),
    State("design-risk-profile", "value"),
    State("design-max-position", "value"),
    State("design-max-sector", "value"),
    State("design-cash-min", "value"),
    State("design-cash-target", "value"),
    State("design-cash-max", "value"),
    State("design-rebalance-freq", "value"),
    State("design-drift-trigger", "value"),
    State("design-rebalance-method", "value"),
    State("design-sector-targets", "data"),
    State("design-region-targets", "data"),
    prevent_initial_call=True,
)
def design_save_policy(
    n_clicks: int,
    portfolio_id: int | None,
    benchmark: str | None,
    risk_profile: str | None,
    max_position: float | None,
    max_sector: float | None,
    cash_min: float | None,
    cash_target: float | None,
    cash_max: float | None,
    rebalance_freq: str | None,
    drift_trigger: float | None,
    rebalance_method: str | None,
    sector_targets: list[dict] | None,
    region_targets: list[dict] | None,
):
    """Save policy, sector targets, and region targets to DB after validation."""
    if portfolio_id is None or n_clicks == 0:
        raise PreventUpdate

    # Server-side validation (defensive)
    errors = []

    # Cash range validation
    if cash_min is not None and cash_target is not None and cash_min > cash_target:
        errors.append("Cash min > target")
    if cash_target is not None and cash_max is not None and cash_target > cash_max:
        errors.append("Cash target > max")
    if cash_min is not None and cash_max is not None and cash_min > cash_max:
        errors.append("Cash min > max")

    for val, name in [(cash_min, "cash_min"), (cash_target, "cash_target"), (cash_max, "cash_max")]:
        if val is not None and (val < 0 or val > 100):
            errors.append(f"{name} out of [0, 100]")

    # Sector targets validation
    if sector_targets:
        for idx, row in enumerate(sector_targets):
            target = row.get("target_pct")
            min_pct = row.get("min_pct")
            max_pct = row.get("max_pct")

            for val, field in [(target, "target"), (min_pct, "min"), (max_pct, "max")]:
                if val is not None and (val < 0 or val > 100):
                    errors.append(f"Sector {idx + 1} {field} out of [0, 100]")

            if min_pct is not None and target is not None and min_pct > target:
                errors.append(f"Sector {idx + 1}: min > target")
            if target is not None and max_pct is not None and target > max_pct:
                errors.append(f"Sector {idx + 1}: target > max")
            if min_pct is not None and max_pct is not None and min_pct > max_pct:
                errors.append(f"Sector {idx + 1}: min > max")

    # Region targets validation
    if region_targets:
        for idx, row in enumerate(region_targets):
            target = row.get("target_pct")
            min_pct = row.get("min_pct")
            max_pct = row.get("max_pct")

            for val, field in [(target, "target"), (min_pct, "min"), (max_pct, "max")]:
                if val is not None and (val < 0 or val > 100):
                    errors.append(f"Region {idx + 1} {field} out of [0, 100]")

            if min_pct is not None and target is not None and min_pct > target:
                errors.append(f"Region {idx + 1}: min > target")
            if target is not None and max_pct is not None and target > max_pct:
                errors.append(f"Region {idx + 1}: target > max")
            if min_pct is not None and max_pct is not None and min_pct > max_pct:
                errors.append(f"Region {idx + 1}: min > max")

    if errors:
        return f"Validation failed: {', '.join(errors)}"

    # Prepare policy dict
    policy = {
        "benchmark_ticker": benchmark,
        "risk_profile": risk_profile,
        "cash_min_pct": cash_min,
        "cash_target_pct": cash_target,
        "cash_max_pct": cash_max,
        "max_position_pct": max_position,
        "max_sector_pct": max_sector,
        "rebalance_freq": rebalance_freq,
        "drift_trigger_pct": drift_trigger,
        "rebalance_method": rebalance_method,
    }

    # Clean sector targets (filter out blank rows)
    # Note: Blank rows are ignored during save - they are UI-only
    cleaned_sector_targets = _filter_blank_rows(sector_targets or [], "sector")

    # Clean region targets (filter out blank rows)
    cleaned_region_targets = _filter_blank_rows(region_targets or [], "region")

    # Save to DB
    try:
        save_policy_snapshot(int(portfolio_id), policy, cleaned_sector_targets, cleaned_region_targets)
        return f"Policy saved successfully for portfolio_id={portfolio_id}"
    except Exception as e:
        return f"Error saving policy: {str(e)}"
