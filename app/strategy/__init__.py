"""Strategy plugin system for backtesting."""

from app.strategy.registry import get_strategies, get_strategy_by_key

__all__ = ["get_strategies", "get_strategy_by_key"]
