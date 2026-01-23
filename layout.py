from dash import html, dcc




def build_layout() -> html.Div:
    return html.Div(
        children=[
            dcc.Location(id="url"),
            html.Div(id="page-content"),
        ],
    style={"maxWidth": "1200px", "margin": "0 auto"},
)