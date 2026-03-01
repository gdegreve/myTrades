"""EMA Trend Following strategy."""

from app.strategy.types import StrategyDef, ParamSpec


def get_definition() -> StrategyDef:
    """Get strategy definition with parameters."""
    param_specs = [
        # Main params
        ParamSpec(
            id="ema_trend",
            label="Trend EMA Period",
            group="main",
            ptype="int",
            default=200,
            min_val=50,
            max_val=300,
            step=10,
        ),
        ParamSpec(
            id="ema_signal",
            label="Signal EMA Period",
            group="main",
            ptype="int",
            default=50,
            min_val=10,
            max_val=100,
            step=5,
        ),
        # Filter params
        ParamSpec(
            id="use_adx",
            label="Enable ADX Filter",
            group="filters",
            ptype="bool",
            default=True,
        ),
        ParamSpec(
            id="adx_min",
            label="ADX Min Threshold",
            group="filters",
            ptype="int",
            default=20,
            min_val=10,
            max_val=50,
            step=5,
        ),
        # Stop params
        ParamSpec(
            id="stop_loss_pct",
            label="Stop Loss %",
            group="stops",
            ptype="float",
            default=0.10,
            min_val=0.0,
            max_val=0.5,
            step=0.01,
        ),
        ParamSpec(
            id="trailing_stop_pct",
            label="Trailing Stop %",
            group="stops",
            ptype="float",
            default=0.06,
            min_val=0.0,
            max_val=0.5,
            step=0.01,
        ),
    ]

    default_params = {spec.id: spec.default for spec in param_specs}

    return StrategyDef(
        key="ema_trend_following",
        name="EMA Trend Following",
        description="Follow price trends using EMA crossovers. Buy when signal EMA crosses above trend EMA, with ADX confirmation.",
        param_specs=param_specs,
        default_params=default_params,
    )
