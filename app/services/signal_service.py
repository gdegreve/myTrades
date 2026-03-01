"""Live signal evaluation for portfolio positions and watchlist tickers.

Two modes:
  Position mode  – ticker is held.  Evaluates stop-loss / take-profit against
                   the real average entry price (native currency).
  Watchlist mode – ticker is watched but not held.  Evaluates entry conditions
                   (e.g. EMA crossover) so the user knows when to buy.

Currency note:
  get_latest_daily_closes_cached returns prices in the ticker's *native*
  currency (no FX conversion yet).  avg_cost from compute_positions is in EUR.
  To keep the comparison correct we derive the native avg cost directly from
  the trades list (using the `price` column, not `price_eur`).
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_position_signal(
    ticker: str,
    saved_strategy: dict,
    current_price: float,
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate live signal for a ticker that is currently held.

    Args:
        ticker:          Uppercase ticker symbol.
        saved_strategy:  Row from strategy_repo.get_saved_strategy_by_id()
                         (must contain ``params`` dict).
        current_price:   Latest native-currency close from market_data.
        trades:          Full trade list for the portfolio (from list_trades).

    Returns:
        Dict with keys: signal, reason, entry_price, stop_price, target_price,
        current_return_pct.
    """
    entry_price = _native_avg_cost(trades, ticker)
    if entry_price is None or entry_price == 0:
        return _no_data("Entry price not available")

    params = saved_strategy.get("params", {})
    stop_loss_pct = params.get("stop_loss_pct", 0.0)
    take_profit_pct = params.get("take_profit_pct", 0.0)

    current_return = current_price / entry_price - 1.0

    stop_price = round(entry_price * (1 - stop_loss_pct), 2) if stop_loss_pct else None
    target_price = round(entry_price * (1 + take_profit_pct), 2) if take_profit_pct else None

    # --- stop-loss check -------------------------------------------------
    if stop_loss_pct > 0 and current_return <= -stop_loss_pct:
        return {
            "signal": "SELL",
            "reason": (
                f"Stop loss hit: {current_return * 100:+.1f}% "
                f"(limit: -{stop_loss_pct * 100:.1f}%)"
            ),
            "entry_price": round(entry_price, 2),
            "stop_price": stop_price,
            "target_price": target_price,
            "current_return_pct": round(current_return * 100, 2),
        }

    # --- take-profit check -----------------------------------------------
    if take_profit_pct > 0 and current_return >= take_profit_pct:
        return {
            "signal": "SELL",
            "reason": (
                f"Take profit hit: {current_return * 100:+.1f}% "
                f"(target: +{take_profit_pct * 100:.1f}%)"
            ),
            "entry_price": round(entry_price, 2),
            "stop_price": stop_price,
            "target_price": target_price,
            "current_return_pct": round(current_return * 100, 2),
        }

    # --- hold ------------------------------------------------------------
    levels = []
    if stop_price:
        levels.append(f"SL {stop_price}")
    if target_price:
        levels.append(f"TP {target_price}")
    levels_str = " | ".join(levels)

    return {
        "signal": "HOLD",
        "reason": f"P&L {current_return * 100:+.1f}% | {levels_str}",
        "entry_price": round(entry_price, 2),
        "stop_price": stop_price,
        "target_price": target_price,
        "current_return_pct": round(current_return * 100, 2),
    }


def evaluate_watchlist_signal(
    ticker: str,
    saved_strategy: dict,
) -> dict[str, Any]:
    """Evaluate entry conditions for a watchlist ticker (not yet held).

    Fetches recent OHLCV, runs the strategy's signal generator, and checks
    whether the *latest* bar produced an entry signal.

    Args:
        ticker:         Uppercase ticker symbol.
        saved_strategy: Row from strategy_repo (must have base_strategy_key + params).

    Returns:
        Dict with keys: signal, reason (entry_price / stop_price / target_price
        are None for watchlist tickers).
    """
    strategy_key = saved_strategy.get("base_strategy_key", "")
    params = saved_strategy.get("params", {})

    try:
        from app.services.technical_service import get_ohlcv_data
        from app.services.backtest_service import generate_signals

        df, error = get_ohlcv_data(ticker, "3mo")
        if error or df is None or df.empty:
            return _no_data(f"Cannot fetch data: {error}")

        signals = generate_signals(strategy_key, df, params)

        # Walk backwards: find the most recent non-zero signal
        last_sig = 0
        for val in reversed(signals.values):
            if val != 0:
                last_sig = int(val)
                break

        if last_sig == 1:
            return {
                "signal": "BUY",
                "reason": "Entry conditions met — ready to buy",
                "entry_price": None,
                "stop_price": None,
                "target_price": None,
                "current_return_pct": None,
            }

        return {
            "signal": "HOLD",
            "reason": "Waiting for entry signal",
            "entry_price": None,
            "stop_price": None,
            "target_price": None,
            "current_return_pct": None,
        }

    except Exception as e:
        return _no_data(f"Signal eval error: {e}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _native_avg_cost(trades: list[dict[str, Any]], ticker: str) -> float | None:
    """Compute weighted-average cost in *native* currency for a ticker.

    Uses the ``price`` column (original currency) rather than ``price_eur``
    so the result is directly comparable to yfinance close prices.

    Commission is converted back to native currency via the stored fx_rate.
    """
    total_shares = 0.0
    total_cost = 0.0  # native currency

    for trade in trades:
        if trade.get("ticker") != ticker:
            continue

        shares = trade.get("shares") or 0.0
        price = trade.get("price") or 0.0          # native
        commission = trade.get("commission") or 0.0  # EUR
        fx_rate = trade.get("fx_rate") or 1.0        # EUR/native

        # commission is stored in EUR; convert back to native
        commission_native = commission / fx_rate if fx_rate != 0 else commission

        if trade.get("transaction_type") == "buy":
            total_cost += shares * price + commission_native
            total_shares += shares
        elif trade.get("transaction_type") == "sell":
            if total_shares > 0:
                reduction_ratio = min(shares / total_shares, 1.0)
                total_cost *= 1 - reduction_ratio
                total_shares -= shares

    if total_shares > 0.0001:
        return total_cost / total_shares
    return None


def _no_data(reason: str) -> dict[str, Any]:
    return {
        "signal": "DATA",
        "reason": reason,
        "entry_price": None,
        "stop_price": None,
        "target_price": None,
        "current_return_pct": None,
    }
