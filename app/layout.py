from dash import html, dcc


def _nav_group(title: str, links: list[tuple[str, str]]) -> html.Div:
    return html.Div(
        children=[
            html.Div(title, style={"fontWeight": "600", "marginTop": "14px"}),
            html.Div(
                [
                    dcc.Link(
                        label,
                        href=href,
                        style={"display": "block", "margin": "6px 0 6px 14px"},
                    )
                    for label, href in links
                ]
            ),
        ]
    )


def build_layout() -> html.Div:
    sidebar = html.Div(
        children=[
            html.H3("MyTrading"),
            html.Hr(),
            _nav_group(
                "Portfolio",
                [
                    ("Overview", "/portfolio/overview"),
                    ("Manage", "/portfolio/manage"),
                    ("Signals", "/portfolio/signals"),
                ],
            ),
            _nav_group(
                "Analytics",
                [
                    ("Fundamentals", "/analytics/fundamentals"),
                    ("Technical", "/analytics/technical"),
                ],
            ),
            _nav_group(
                "Tools",
                [
                    ("Settings", "/tools/settings"),
                ],
            ),
        ],
        style={
            "width": "240px",
            "padding": "16px",
            "borderRight": "1px solid #ddd",
            "height": "100vh",
            "boxSizing": "border-box",
        },
    )

    content = html.Div(
        id="page-content",
        style={"padding": "16px", "flex": "1", "boxSizing": "border-box"},
    )

    return html.Div(
        children=[
            dcc.Location(id="url"),
            html.Div([sidebar, content], style={"display": "flex"}),
        ]
    )
