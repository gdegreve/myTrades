from __future__ import annotations

from dash import dcc, html

# Navigation dropdown groups for header
PORTFOLIO_SUBNAV = [
    ("Overview", "/portfolio/overview"),
    ("Holdings", "/portfolio/holdings"),
    ("Signals", "/portfolio/signals"),
    ("Rebalance", "/portfolio/rebalance"),
    ("Design", "/portfolio/design"),
]

MARKET_SUBNAV = [
    ("Today", "/today"),
    ("Market", "/market"),
    ("Exchange", "/analytics/fundamentals"),
]

ANALYSIS_SUBNAV = [
    ("Fundamental", "/analysis/fundamental"),
    ("Technical", "/analysis/technical"),
]

SETTINGS_SUBNAV = [
    ("Wallets", "/tools/settings"),
]


def _nav_dropdown(label: str, items: list[tuple[str, str]]) -> html.Div:
    """Build a hover-based dropdown menu for the header."""
    return html.Div(
        className="nav-dropdown",
        children=[
            html.Div(label, className="nav-dropdown-toggle"),
            html.Div(
                className="nav-dropdown-menu",
                children=[
                    dcc.Link(item_label, href=item_href, className="nav-dropdown-item")
                    for item_label, item_href in items
                ],
            ),
        ],
    )


def build_layout() -> html.Div:
    # Global active context for cross-page state (portfolio_id, ticker, timeframe)
    ui_active_context = dcc.Store(
        id="ui-active-context",
        storage_type="memory",
        data={"portfolio_id": 1, "ticker": None, "timeframe": "1y"}
    )

    return html.Div(
        children=[
            dcc.Location(id="url"),
            ui_active_context,
            html.Div(
                className="app-shell",
                children=[
                    # Top navigation header
                    html.Header(
                        className="app-header",
                        children=[
                            html.Div(
                                className="header-inner",
                                children=[
                                    # Left: Brand
                                    dcc.Link(
                                        href="/today",
                                        className="header-brand",
                                        children=[
                                            html.Div(className="brand-mark"),
                                            html.Span("MyTrading", className="brand-text"),
                                        ],
                                    ),
                                    # Center: Search placeholder
                                    html.Div(
                                        className="header-search",
                                        children=[
                                            dcc.Input(
                                                type="text",
                                                placeholder="Search symbols, strategies...",
                                                className="search-input",
                                                disabled=True,
                                            ),
                                        ],
                                    ),
                                    # Right: Navigation dropdowns
                                    html.Nav(
                                        className="header-nav",
                                        children=[
                                            _nav_dropdown("Portfolio", PORTFOLIO_SUBNAV),
                                            _nav_dropdown("Market", MARKET_SUBNAV),
                                            _nav_dropdown("Analysis", ANALYSIS_SUBNAV),
                                            _nav_dropdown("Settings", SETTINGS_SUBNAV),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    # Main content area
                    html.Main(
                        id="main",
                        className="main",
                        children=html.Div(id="page-content", className="page"),
                    ),
                ],
            ),
        ]
    )


# All sidebar callbacks removed - header navigation is CSS-only (hover-based dropdowns)
