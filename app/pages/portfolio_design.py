from __future__ import annotations
import dash_bootstrap_components as dbc

from dash import dcc, html, Input, Output, State, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate

from app.db.portfolio_repo import list_portfolios
from app.db.policy_repo import load_policy_snapshot, save_policy_snapshot


def layout() -> html.Div:
    return html.Div(
        children=[
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
            html.Div(id="design-status", className="hint-text", style={"marginTop": "6px"}),

            html.Hr(style={"margin": "16px 0"}),

            html.Div(
                className="card",
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
                className="card",
                style={"marginTop": "14px"},
                children=[
                    html.Div(
                        className="card-title-row",
                        children=[
                            html.Div("Target Allocation (Sector)", className="card-title"),
                            html.Div("Editable table. Click Save policy to persist changes.", className="hint-text"),
                        ],
                    ),
                    DataTable(
                        id="design-sector-targets",
                        columns=[
                            {"name": "Sector", "id": "sector"},
                            {"name": "Target %", "id": "target_pct", "type": "numeric", "editable": True},
                            {"name": "Min %", "id": "min_pct", "type": "numeric", "editable": True},
                            {"name": "Max %", "id": "max_pct", "type": "numeric", "editable": True},
                        ],
                        data=[],
                        page_size=12,
                        style_table={"overflowX": "auto"},
                        style_cell={"padding": "10px", "textAlign": "left"},
                        style_header={"fontWeight": "600"},
                    ),
                ],
            ),

            html.Div(
                className="grid-2",
                style={"marginTop": "14px"},
                children=[
                    html.Div(
                        className="card",
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
                style={"marginTop": "14px"},
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


# Callback 2: load policy + targets for selected portfolio (single source of truth for design-status)
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
    Output("design-currency", "value"),
    Output("design-status", "children"),
    Input("design-portfolio", "value"),
)
def design_load_policy(portfolio_id: int | None):
    if portfolio_id is None:
        raise PreventUpdate

    snapshot = load_policy_snapshot(int(portfolio_id))

    policy = snapshot.get("policy", {}) or {}
    targets = snapshot.get("sector_targets", []) or []

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
        targets,
        snapshot.get("base_currency", "EUR"),
        f"Loaded policy for portfolio_id={portfolio_id}.",
    )


# Callback 3: validate form and enable/disable save button
@callback(
    Output("design-save", "disabled"),
    Input("design-portfolio", "value"),
    Input("design-cash-min", "value"),
    Input("design-cash-target", "value"),
    Input("design-cash-max", "value"),
    Input("design-sector-targets", "data"),
)
def design_validate_form(
    portfolio_id: int | None,
    cash_min: float | None,
    cash_target: float | None,
    cash_max: float | None,
    sector_targets: list[dict] | None,
):
    """Enable save button only if portfolio selected and basic validation passes."""
    if portfolio_id is None:
        return True  # disabled

    # Check cash range consistency
    if cash_min is not None and cash_target is not None and cash_min > cash_target:
        return True
    if cash_target is not None and cash_max is not None and cash_target > cash_max:
        return True
    if cash_min is not None and cash_max is not None and cash_min > cash_max:
        return True

    # Check cash percentages in [0, 100]
    for val in [cash_min, cash_target, cash_max]:
        if val is not None and (val < 0 or val > 100):
            return True

    # Check sector targets consistency (min <= target <= max)
    if sector_targets:
        for row in sector_targets:
            target = row.get("target_pct")
            min_pct = row.get("min_pct")
            max_pct = row.get("max_pct")

            # Skip rows with all None (no validation needed)
            if target is None and min_pct is None and max_pct is None:
                continue

            # Check percentages in [0, 100]
            for val in [target, min_pct, max_pct]:
                if val is not None and (val < 0 or val > 100):
                    return True

            # Check ordering: min <= target <= max (when values exist)
            if min_pct is not None and target is not None and min_pct > target:
                return True
            if target is not None and max_pct is not None and target > max_pct:
                return True
            if min_pct is not None and max_pct is not None and min_pct > max_pct:
                return True

    return False  # enabled


# Callback 4: save policy + sector targets
@callback(
    Output("design-status", "children", allow_duplicate=True),
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
):
    """Save policy and sector targets to DB after validation."""
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

    # Clean sector targets (filter out rows with all None values)
    cleaned_targets = []
    if sector_targets:
        for row in sector_targets:
            target = row.get("target_pct")
            min_pct = row.get("min_pct")
            max_pct = row.get("max_pct")
            if target is not None or min_pct is not None or max_pct is not None:
                cleaned_targets.append(row)

    # Save to DB
    try:
        save_policy_snapshot(int(portfolio_id), policy, cleaned_targets)
        return f"Policy saved successfully for portfolio_id={portfolio_id}."
    except Exception as e:
        return f"Error saving policy: {str(e)}"
