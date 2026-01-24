from __future__ import annotations

from dash import dcc, html, Input, Output, State, callback
from dash.dash_table import DataTable
from dash.exceptions import PreventUpdate

from app.db.portfolio_repo import list_portfolios
from app.db.policy_repo import load_policy_snapshot


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
                                    dcc.Dropdown(
                                        id="design-benchmark",
                                        options=[
                                            {"label": "VWCE (All-World)", "value": "VWCE"},
                                            {"label": "S&P 500 (SPY)", "value": "SPY"},
                                            {"label": "STOXX Europe 600", "value": "SXXP"},
                                        ],
                                        value=None,
                                        clearable=False,
                                    ),
                                ]
                            ),
                            html.Div(
                                children=[
                                    html.Div("Risk profile", className="field-label"),
                                    dcc.Dropdown(
                                        id="design-risk-profile",
                                        options=[
                                            {"label": "Conservative", "value": "conservative"},
                                            {"label": "Balanced", "value": "balanced"},
                                            {"label": "Aggressive", "value": "aggressive"},
                                        ],
                                        value=None,
                                        clearable=False,
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
                            html.Div("Read-only (Step 4). Save comes in Step 5.", className="hint-text"),
                        ],
                    ),
                    DataTable(
                        id="design-sector-targets",
                        columns=[
                            {"name": "Sector", "id": "sector"},
                            {"name": "Target %", "id": "target_pct"},
                            {"name": "Min %", "id": "min_pct"},
                            {"name": "Max %", "id": "max_pct"},
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
                                    dcc.Dropdown(
                                        id="design-rebalance-freq",
                                        options=[
                                            {"label": "Monthly", "value": "monthly"},
                                            {"label": "Quarterly", "value": "quarterly"},
                                            {"label": "Semi-annually", "value": "semiannual"},
                                            {"label": "Annually", "value": "annual"},
                                        ],
                                        value=None,
                                        clearable=False,
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
                                    dcc.Dropdown(
                                        id="design-rebalance-method",
                                        options=[
                                            {"label": "Contributions-first (preferred)", "value": "contributions_first"},
                                            {"label": "Sell & buy to target", "value": "sell_buy"},
                                        ],
                                        value=None,
                                        clearable=False,
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
        f"Loaded policy for portfolio_id={portfolio_id} (read-only).",
    )
