"""Backtest engine for strategy simulation."""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime

from app.services.technical_service import get_ohlcv_data
from app.strategy import get_strategy_by_key


def run_backtest(
    ticker: str,
    strategy_key: str,
    params: dict,
    timeframe: str,
) -> dict:
    """Run backtest simulation for a strategy.

    Args:
        ticker: Stock ticker symbol
        strategy_key: Strategy key (e.g., "ema_crossover_rsi")
        params: Strategy parameters dict
        timeframe: Period string (e.g., "1y", "6mo")

    Returns:
        Dict with keys:
            - stats: {total_return, max_drawdown, sharpe_ratio, win_rate, num_trades, avg_trade}
            - equity_series: [(date_str, equity_value), ...]
            - trades: [(entry_date, exit_date, return_pct), ...]
            - execution_time_ms: float
    """
    start_time = datetime.now()

    # Fetch OHLCV data
    df, error = get_ohlcv_data(ticker, timeframe)
    if error or df is None or df.empty:
        raise ValueError(error or "No data available")

    if len(df) < 50:
        raise ValueError("Not enough candles for backtest (minimum 50 required)")

    # Generate signals based on strategy
    signals = generate_signals(strategy_key, df, params)
    if signals is None or signals.empty:
        raise ValueError("Signal generation failed")

    # Run simulation
    results = simulate_trades(df, signals, params)

    # Compute stats
    stats = compute_stats(results)

    # Prepare equity series for charting
    equity_series = [
        (date.strftime("%Y-%m-%d"), float(equity))
        for date, equity in zip(results["equity"].index, results["equity"])
    ]

    # Extract trades list
    trades_list = [
        (
            entry.strftime("%Y-%m-%d"),
            exit.strftime("%Y-%m-%d"),
            float(ret),
        )
        for entry, exit, ret in results["trades"]
    ]

    execution_time = (datetime.now() - start_time).total_seconds() * 1000

    return {
        "stats": stats,
        "equity_series": equity_series,
        "trades": trades_list,
        "execution_time_ms": execution_time,
    }


def generate_signals(strategy_key: str, df: pd.DataFrame, params: dict) -> pd.Series:
    """Generate buy/sell signals based on strategy.

    Args:
        strategy_key: Strategy identifier
        df: DataFrame with OHLC + indicators
        params: Strategy parameters

    Returns:
        Series of 1 (long), 0 (flat), -1 (exit trigger)
    """
    if strategy_key == "ema_crossover_rsi":
        return _generate_ema_crossover_rsi(df, params)
    elif strategy_key == "ema_trend_following":
        return _generate_ema_trend_following(df, params)
    elif strategy_key == "rsi_mean_reversion":
        return _generate_rsi_mean_reversion(df, params)
    else:
        raise ValueError(f"Unknown strategy: {strategy_key}")


def _generate_ema_crossover_rsi(df: pd.DataFrame, params: dict) -> pd.Series:
    """EMA Crossover + RSI filter signals."""
    # Get EMAs (already computed in df if using technical_service)
    ema_fast_key = f"EMA_{params.get('ema_fast', 12)}"
    ema_slow_key = f"EMA_{params.get('ema_slow', 26)}"

    # If not present, compute
    if ema_fast_key not in df.columns:
        df[ema_fast_key] = df["Close"].ewm(span=params.get("ema_fast", 12), adjust=False).mean()
    if ema_slow_key not in df.columns:
        df[ema_slow_key] = df["Close"].ewm(span=params.get("ema_slow", 26), adjust=False).mean()

    # Crossover logic
    signal = pd.Series(0, index=df.index)
    cross_up = (df[ema_fast_key] > df[ema_slow_key]) & (df[ema_fast_key].shift(1) <= df[ema_slow_key].shift(1))
    cross_down = (df[ema_fast_key] < df[ema_slow_key]) & (df[ema_fast_key].shift(1) >= df[ema_slow_key].shift(1))

    # Apply RSI filter if enabled
    if params.get("use_rsi_filter", True):
        rsi_min = params.get("rsi_min", 50)
        rsi_max = params.get("rsi_max", 80)
        rsi_ok = (df["RSI"] >= rsi_min) & (df["RSI"] <= rsi_max)
        cross_up = cross_up & rsi_ok

    signal[cross_up] = 1
    signal[cross_down] = -1

    return signal


def _generate_ema_trend_following(df: pd.DataFrame, params: dict) -> pd.Series:
    """EMA Trend Following signals."""
    ema_trend_period = params.get("ema_trend", 200)
    ema_signal_period = params.get("ema_signal", 50)

    ema_trend_key = f"EMA_{ema_trend_period}"
    ema_signal_key = f"EMA_{ema_signal_period}"

    if ema_trend_key not in df.columns:
        df[ema_trend_key] = df["Close"].ewm(span=ema_trend_period, adjust=False).mean()
    if ema_signal_key not in df.columns:
        df[ema_signal_key] = df["Close"].ewm(span=ema_signal_period, adjust=False).mean()

    signal = pd.Series(0, index=df.index)

    # Entry: Close > trend EMA and signal EMA rising
    entry_cond = (df["Close"] > df[ema_trend_key]) & (df["Close"] > df[ema_signal_key])

    # Exit: Close < signal EMA
    exit_cond = df["Close"] < df[ema_signal_key]

    # Apply ADX filter if enabled
    if params.get("use_adx", True) and "ADX" in df.columns:
        adx_min = params.get("adx_min", 20)
        entry_cond = entry_cond & (df["ADX"] >= adx_min)

    signal[entry_cond] = 1
    signal[exit_cond] = -1

    return signal


def _generate_rsi_mean_reversion(df: pd.DataFrame, params: dict) -> pd.Series:
    """RSI Mean Reversion signals."""
    rsi_period = params.get("rsi_period", 14)
    oversold = params.get("oversold", 30)
    overbought = params.get("overbought", 70)

    signal = pd.Series(0, index=df.index)

    # Entry: RSI <= oversold
    entry_cond = df["RSI"] <= oversold

    # Apply trend filter if enabled
    if params.get("use_trend_filter", True):
        ema_trend_period = params.get("ema_trend", 200)
        ema_trend_key = f"EMA_{ema_trend_period}"

        if ema_trend_key not in df.columns:
            df[ema_trend_key] = df["Close"].ewm(span=ema_trend_period, adjust=False).mean()

        entry_cond = entry_cond & (df["Close"] > df[ema_trend_key])

    # Exit: RSI >= 50 (mean reversion target)
    exit_cond = df["RSI"] >= 50

    signal[entry_cond] = 1
    signal[exit_cond] = -1

    return signal


def simulate_trades(df: pd.DataFrame, signals: pd.Series, params: dict) -> dict:
    """Simulate trades with position management and stops.

    Args:
        df: DataFrame with OHLC data
        signals: Series with 1 (entry), -1 (exit), 0 (hold)
        params: Strategy parameters (for stops)

    Returns:
        Dict with equity series and trades list
    """
    position = 0  # 0 = flat, 1 = long
    entry_price = 0.0
    entry_date = None
    trades = []
    equity = [1.0]  # Start with 1.0 (100%)

    stop_loss_pct = params.get("stop_loss_pct", 0.0)
    take_profit_pct = params.get("take_profit_pct", 0.0)
    trailing_stop_pct = params.get("trailing_stop_pct", 0.0)
    highest_since_entry = 0.0

    for i in range(1, len(df)):
        date = df.index[i]
        close = df["Close"].iloc[i]
        signal = signals.iloc[i]

        # Check stops if in position
        if position == 1:
            # Stop loss
            if stop_loss_pct > 0:
                if close / entry_price - 1 <= -stop_loss_pct:
                    # Stop hit
                    trade_return = close / entry_price - 1
                    equity.append(equity[-1] * (1 + trade_return))
                    trades.append((entry_date, date, trade_return))
                    position = 0
                    continue

            # Take profit
            if take_profit_pct > 0:
                if close / entry_price - 1 >= take_profit_pct:
                    trade_return = close / entry_price - 1
                    equity.append(equity[-1] * (1 + trade_return))
                    trades.append((entry_date, date, trade_return))
                    position = 0
                    continue

            # Trailing stop
            if trailing_stop_pct > 0:
                highest_since_entry = max(highest_since_entry, close)
                if close / highest_since_entry - 1 <= -trailing_stop_pct:
                    trade_return = close / entry_price - 1
                    equity.append(equity[-1] * (1 + trade_return))
                    trades.append((entry_date, date, trade_return))
                    position = 0
                    continue

        # Signal-based entry/exit
        if signal == 1 and position == 0:
            # Enter long (next day execution)
            position = 1
            entry_price = close
            entry_date = date
            highest_since_entry = close
            equity.append(equity[-1])
        elif signal == -1 and position == 1:
            # Exit long
            trade_return = close / entry_price - 1
            equity.append(equity[-1] * (1 + trade_return))
            trades.append((entry_date, date, trade_return))
            position = 0
        else:
            # Hold
            if position == 1:
                # Update equity based on current position
                current_return = close / entry_price - 1
                equity.append(equity[-1] * (1 + current_return) / (1 + (df["Close"].iloc[i-1] / entry_price - 1)) if i > 1 else equity[-1])
            else:
                equity.append(equity[-1])

    # Close any open position at end
    if position == 1:
        close = df["Close"].iloc[-1]
        trade_return = close / entry_price - 1
        equity[-1] = equity[-1] * (1 + trade_return)
        trades.append((entry_date, df.index[-1], trade_return))

    equity_series = pd.Series(equity, index=df.index)

    return {
        "equity": equity_series,
        "trades": trades,
    }


def compute_stats(results: dict) -> dict:
    """Compute backtest statistics.

    Args:
        results: Dict with equity series and trades

    Returns:
        Dict with stats: total_return, max_drawdown, sharpe_ratio, win_rate, num_trades, avg_trade
    """
    equity = results["equity"]
    trades = results["trades"]

    # Total return
    total_return = (equity.iloc[-1] - 1.0) * 100

    # Max drawdown
    cummax = equity.cummax()
    drawdown = (equity - cummax) / cummax
    max_drawdown = drawdown.min() * 100

    # Sharpe ratio (annualized)
    returns = equity.pct_change().dropna()
    if len(returns) > 0 and returns.std() > 0:
        sharpe_ratio = (returns.mean() / returns.std()) * np.sqrt(252)
    else:
        sharpe_ratio = 0.0

    # Trade stats
    num_trades = len(trades)
    if num_trades > 0:
        trade_returns = [t[2] for t in trades]
        avg_trade = np.mean(trade_returns) * 100
        win_rate = (sum(1 for r in trade_returns if r > 0) / num_trades) * 100
    else:
        avg_trade = 0.0
        win_rate = 0.0

    return {
        "total_return": round(total_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "win_rate": round(win_rate, 1),
        "num_trades": num_trades,
        "avg_trade": round(avg_trade, 2),
    }
