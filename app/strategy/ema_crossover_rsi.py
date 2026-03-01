"""EMA Crossover + RSI Filter strategy."""

from app.strategy.types import StrategyDef, ParamSpec


def get_definition() -> StrategyDef:
    """Get strategy definition with parameters."""
    param_specs = [
        # Main params
        ParamSpec(
            id="ema_fast",
            label="Fast EMA Period",
            group="main",
            ptype="int",
            default=12,
            min_val=5,
            max_val=50,
            step=1,
        ),
        ParamSpec(
            id="ema_slow",
            label="Slow EMA Period",
            group="main",
            ptype="int",
            default=26,
            min_val=10,
            max_val=200,
            step=1,
        ),
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
        # Filter params
        ParamSpec(
            id="use_rsi_filter",
            label="Enable RSI Filter",
            group="filters",
            ptype="bool",
            default=True,
        ),
        ParamSpec(
            id="rsi_min",
            label="RSI Min Threshold",
            group="filters",
            ptype="int",
            default=50,
            min_val=0,
            max_val=100,
            step=1,
        ),
        ParamSpec(
            id="rsi_max",
            label="RSI Max Threshold",
            group="filters",
            ptype="int",
            default=80,
            min_val=0,
            max_val=100,
            step=1,
        ),
        # Stop params
        ParamSpec(
            id="stop_loss_pct",
            label="Stop Loss %",
            group="stops",
            ptype="float",
            default=0.08,
            min_val=0.0,
            max_val=0.5,
            step=0.01,
        ),
        ParamSpec(
            id="take_profit_pct",
            label="Take Profit %",
            group="stops",
            ptype="float",
            default=0.15,
            min_val=0.0,
            max_val=1.0,
            step=0.01,
        ),
        ParamSpec(
            id="trailing_stop_pct",
            label="Trailing Stop % (0=disabled)",
            group="stops",
            ptype="float",
            default=0.0,
            min_val=0.0,
            max_val=0.5,
            step=0.01,
        ),
    ]

    default_params = {spec.id: spec.default for spec in param_specs}

    return StrategyDef(
        key="ema_crossover_rsi",
        name="EMA Crossover + RSI",
        description="Buy when fast EMA crosses above slow EMA, with optional RSI filter. Sell on opposite cross or stops.",
        param_specs=param_specs,
        default_params=default_params,
    )
