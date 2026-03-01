from __future__ import annotations

from dash import dcc, html, Input, Output, State, callback
from dash.exceptions import PreventUpdate

# Tree-style navigation groups (Option A)
NAV = [
    (
        "MENU",
        [
            ("Dashboard", "/portfolio/overview", "fa-solid fa-house"),
            ("Exchange", "/analytics/fundamentals", "fa-solid fa-right-left"),
            ("Market", "/market", "fa-solid fa-chart-line"),
            ("Wallets", "/tools/settings", "fa-solid fa-wallet"),
            #("Analysis", "/analysis/fundamental", "fa-solid fa-magnifying-glass-chart"),
            # Portfolio becomes a parent with a submenu (still clickable)
            ("Portfolio", "/portfolio/overview", "fa-solid fa-briefcase"),
        ],
    ),
    (
        "SUPPORT",
        [
            ("Community", "/support/community", "fa-solid fa-users"),
            ("Help & Support", "/support/help", "fa-regular fa-circle-question"),
        ],
    ),
]

ANALYSIS_SUBNAV = [
    ("Fundamental", "/analysis/fundamental"),
    ("Technical", "/analysis/technical"),
]

PORTFOLIO_SUBNAV = [
    ("Overview", "/portfolio/overview"),
    ("Design", "/portfolio/design"),
    ("Holdings", "/portfolio/holdings"),
    ("Signals", "/portfolio/signals"),
    ("Rebalance", "/portfolio/rebalance"),
]


def _nav_item(label: str, href: str, icon: str, pathname: str) -> dcc.Link:
    is_active = pathname == href or (pathname == "/" and href == "/portfolio/overview")
    cls = "nav-item active" if is_active else "nav-item"

    return dcc.Link(
        href=href,
        className=cls,
        children=[
            html.I(className=f"nav-icon {icon}"),
            html.Span(label, className="nav-label"),
        ],
    )


def _is_portfolio_path(pathname: str) -> bool:
    return (pathname or "").startswith("/portfolio/")


def _is_analysis_path(pathname: str) -> bool:
    return (pathname or "").startswith("/analysis/")


def _portfolio_parent_row(pathname: str, is_open: bool) -> html.Div:
    active_cls = "nav-item active" if _is_portfolio_path(pathname) else "nav-item"

    return html.Div(
        className="nav-parent-row",
        children=[
            html.Div(
                id="portfolio-parent-label",
                className=active_cls,
                children=[
                    html.I(className="nav-icon fa-solid fa-briefcase"),
                    html.Span("Portfolio", className="nav-label"),
                ],
            ),
            html.Button(
                id="portfolio-menu-toggle",
                className="nav-chevron",
                title="Toggle portfolio menu",
                children=html.I(
                    className="fa-solid fa-chevron-down" if is_open else "fa-solid fa-chevron-right"
                ),
            ),
        ],
    )


def _portfolio_children(pathname: str) -> html.Div:
    return html.Div(
        className="nav-submenu",
        children=[
            dcc.Link(
                href=href,
                className=("nav-item active nav-subitem" if pathname == href else "nav-item nav-subitem"),
                children=[html.Span(label, className="nav-label")],
            )
            for label, href in PORTFOLIO_SUBNAV
        ],
    )


def _analysis_parent_row(pathname: str, is_open: bool) -> html.Div:
    active_cls = "nav-item active" if _is_analysis_path(pathname) else "nav-item"

    return html.Div(
        className="nav-parent-row",
        children=[
            html.Div(
                id="analysis-parent-label",
                className=active_cls,
                children=[
                    html.I(className="nav-icon fa-solid fa-magnifying-glass-chart"),
                    html.Span("Analysis", className="nav-label"),
                ],
            ),
            html.Button(
                id="analysis-menu-toggle",
                className="nav-chevron",
                title=f"Toggle analysis menu | open={is_open}",
                children=html.I(
                    className="fa-solid fa-chevron-down" if is_open else "fa-solid fa-chevron-right"
                ),
            ),
        ],
    )


def _analysis_children(pathname: str) -> html.Div:
    return html.Div(
        className="nav-submenu",
        children=[
            dcc.Link(
                href=href,
                className=("nav-item active nav-subitem" if pathname == href else "nav-item nav-subitem"),
                children=[html.Span(label, className="nav-label")],
            )
            for label, href in ANALYSIS_SUBNAV
        ],
    )


def build_layout() -> html.Div:
    # Persistent across refresh
    sidebar_state = dcc.Store(id="sidebar-collapsed", storage_type="local", data=False)

    # Memory-only state for Portfolio submenu
    portfolio_menu_state = dcc.Store(
        id="portfolio-menu-open",
        data=None,
    )

    # Memory-only state for Analysis submenu
    analysis_menu_state = dcc.Store(
        id="analysis-menu-open",
        data=None,
    )

    return html.Div(
        children=[
            dcc.Location(id="url"),
            sidebar_state,
            portfolio_menu_state,
            analysis_menu_state,
            html.Div(
                className="app-shell",
                children=[
                    html.Aside(
                        id="sidebar",
                        className="sidebar",
                        children=[
                            html.Div(
                                className="sidebar-top",
                                children=[
                                    html.Div(
                                        className="brand-row",
                                        children=[
                                            html.Div(
                                                className="brand",
                                                children=[
                                                    html.Div(className="brand-mark"),
                                                    html.Div(
                                                        className="brand-stack",
                                                        children=[
                                                            html.Span("MyTrading", className="brand-text"),
                                                            html.Span(
                                                                "Trading dashboard",
                                                                className="brand-subtext",
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            ),
                                            html.Button(
                                                id="sidebar-toggle",
                                                className="sidebar-toggle icon-only",
                                                n_clicks=0,
                                                children=html.I(className="fa-solid fa-bars"),
                                                title="Toggle sidebar",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Div(id="sidebar-nav", className="sidebar-nav"),
                        ],
                    ),
                    html.Main(
                        id="main",
                        className="main",
                        children=html.Div(id="page-content", className="page"),
                    ),
                ],
            ),
        ]
    )


@callback(
    Output("sidebar-nav", "children"),
    Input("url", "pathname"),
    Input("sidebar-collapsed", "data"),
    Input("portfolio-menu-open", "data"),
    Input("analysis-menu-open", "data"),
)
def render_sidebar_nav(pathname: str, sidebar_collapsed: bool, portfolio_open: bool, analysis_open: bool):
    pathname = pathname or "/"
    blocks = []

    # Auto-close when leaving section; do NOT force-open while inside (so user can collapse)
    if not _is_portfolio_path(pathname):
        portfolio_open = False
    elif portfolio_open is None:
        portfolio_open = True   # only "default open" when state is truly unset

    if not _is_analysis_path(pathname):
        analysis_open = False
    elif analysis_open is None:
        analysis_open = True    # only "default open" when state is truly unset

    for section_title, items in NAV:
        blocks.append(html.Div(section_title, className="nav-section-title"))

        rendered_items = []
        for label, href, icon in items:
            if label == "Portfolio":
                rendered_items.append(_portfolio_parent_row(pathname, is_open=bool(portfolio_open)))

                # Only show submenu when sidebar is expanded and portfolio menu is open
                if (not sidebar_collapsed) and portfolio_open:
                    rendered_items.append(_portfolio_children(pathname))
            elif label == "Analysis":
                rendered_items.append(_analysis_parent_row(pathname, is_open=bool(analysis_open)))

                # Only show submenu when sidebar is expanded and analysis menu is open
                if (not sidebar_collapsed) and analysis_open:
                    rendered_items.append(_analysis_children(pathname))
            else:
                rendered_items.append(_nav_item(label, href, icon, pathname))

        blocks.append(html.Div(className="nav-section", children=rendered_items))

    return blocks

@callback(
    Output("sidebar-collapsed", "data"),
    Input("sidebar-toggle", "n_clicks"),
    State("sidebar-collapsed", "data"),
    prevent_initial_call=True,
)
def toggle_sidebar(n_clicks: int, collapsed: bool):
    return not bool(collapsed)

@callback(
    Output("sidebar", "className"),
    Output("main", "className"),
    Input("sidebar-collapsed", "data"),
)
def apply_sidebar_state(collapsed: bool):
    if collapsed:
        return "sidebar collapsed", "main collapsed"
    return "sidebar", "main"

@callback(
    Output("portfolio-menu-open", "data"),
    Input("portfolio-menu-toggle", "n_clicks"),
    State("portfolio-menu-open", "data"),
    prevent_initial_call=True,
)
def toggle_portfolio_menu(n_clicks: int, is_open: bool):
    if not n_clicks:
        raise PreventUpdate
    return not bool(is_open)


@callback(
    Output("analysis-menu-open", "data"),
    Input("analysis-menu-toggle", "n_clicks"),
    State("analysis-menu-open", "data"),
    prevent_initial_call=True,
)
def toggle_analysis_menu(n_clicks: int, is_open: bool):
    if not n_clicks:
        raise PreventUpdate
    return not bool(is_open)
