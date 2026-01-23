from dash import Dash
from app.layout import build_layout


app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="MyTrading – Dash",
)


app.layout = build_layout()


if __name__ == "__main__":
    app.run_server(debug=True)