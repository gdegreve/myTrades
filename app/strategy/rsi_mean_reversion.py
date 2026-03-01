"""RSI Mean Reversion strategy."""

from app.strategy.types import StrategyDef, ParamSpec


def get_definition() -> StrategyDef:
    """Get strategy definition with parameters."""
    param_specs = [
        # Main params
        ParamSpec(
            id="rsi_period",
            label="RSI Period",
            group="main",
            ptype="int",
            default=14,
            min_val=5,
            max_val=30,
            step=1,
        ),
        ParamSpec(
            id="oversold",
            label="Oversold Level",
            group="main",
            ptype="int",
            default=30,
            min_val=10,
            max_val=50,
            step=5,
        ),
        ParamSpec(
            id="overbought",
            label="Overbought Level",
            group="main",
            ptype="int",
            default=70,
            min_val=50,
            max_val=90,
            step=5,
        ),
        # Filter params
        ParamSpec(
            id="use_trend_filter",
            label="Enable Trend Filter",
            group="filters",
            ptype="bool",
            default=True,
        ),
        ParamSpec(
            id="ema_trend",
            label="Trend EMA Period",
            group="filters",
            ptype="int",
            default=200,
            min_val=50,
            max_val=300,
            step=10,
        ),
        # Stop params
        ParamSpec(
            id="stop_loss_pct",
            label="Stop Loss %",
            group="stops",
            ptype="float",
            default=0.07,
            min_val=0.0,
            max_val=0.5,
            step=0.01,
        ),
        ParamSpec(
            id="take_profit_pct",
            label="Take Profit %",
            group="stops",
            ptype="float",
            default=0.10,
            min_val=0.0,
            max_val=1.0,
            step=0.01,
        ),
    ]

    default_params = {spec.id: spec.default for spec in param_specs}

    return StrategyDef(
        key="rsi_mean_reversion",
        name="RSI Mean Reversion",
        description="Buy when RSI is oversold, sell when overbought. Works best in ranging markets with optional trend filter.",
        param_specs=param_specs,
        default_params=default_params,
    )
