"""Strategy registry for loading and managing strategy definitions."""

from __future__ import annotations

from app.strategy.types import StrategyDef
from app.strategy import ema_crossover_rsi, ema_trend_following, rsi_mean_reversion


def get_strategies() -> tuple[list[StrategyDef], dict[str, StrategyDef]]:
    """Get all registered strategies.

    Returns:
        Tuple of (list of strategy defs, dict of strategy defs by key)
    """
    strategies = [
        ema_crossover_rsi.get_definition(),
        ema_trend_following.get_definition(),
        rsi_mean_reversion.get_definition(),
    ]

    strategies_by_key = {s.key: s for s in strategies}

    return strategies, strategies_by_key


def get_strategy_by_key(key: str) -> StrategyDef | None:
    """Get a strategy definition by key.

    Args:
        key: Strategy key (e.g., "ema_crossover_rsi")

    Returns:
        StrategyDef if found, None otherwise
    """
    _, strategies_by_key = get_strategies()
    return strategies_by_key.get(key)
