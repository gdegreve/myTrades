"""Signal sizing service for converting signals into trade targets.

Implements two sizing rule sets:
- Rule A: Step-based position sizing (fixed percentage steps)
- Rule B: Risk/ATR-based position sizing (risk-adjusted sizing)

Also computes stop/stop-limit price suggestions based on EOD data.
"""

from __future__ import annotations

import pandas as pd


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """Compute Average True Range (ATR) for stop distance calculation.

    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period (default 14)

    Returns:
        ATR value as float (or 0.0 if insufficient data)
    """
    if len(close) < period + 1:
        return 0.0

    high_low = high - low
    high_close = abs(high - close.shift())
    low_close = abs(low - close.shift())

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]

    return atr if pd.notna(atr) else 0.0


def build_signal_trade_targets(
    portfolio_id: int,
    holdings_rows: list[dict],
    nav_eur: float,
    prices: dict[str, float],
    signals: dict[str, dict],
    assignment_map: dict[str, int],
    saved_strategy_map: dict[int, dict],
    policy: dict,
    ohlcv_data: dict[str, pd.DataFrame] | None = None,
) -> list[dict]:
    """Build signal-based trade targets using configured sizing policy.

    Args:
        portfolio_id: Portfolio ID
        holdings_rows: Current holdings [{ticker, shares, value}, ...]
        nav_eur: Current NAV in EUR
        prices: Dict of {ticker: last_close}
        signals: Dict of {ticker: {signal, strength, confidence, reason}}
        assignment_map: Dict of {ticker: saved_strategy_id}
        saved_strategy_map: Dict of {saved_strategy_id: {base_strategy_key, params}}
        policy: Policy snapshot dict with signal sizing settings
        ohlcv_data: Optional dict of {ticker: OHLCV DataFrame} for ATR calculation

    Returns:
        List of trade suggestion dicts
    """
    sizing_mode = policy.get("signal_sizing_mode", "off")

    if sizing_mode == "off":
        return []

    # Convert holdings to dict for easier lookup
    holdings_map = {h["ticker"]: h for h in holdings_rows}

    # Determine current position weights
    position_weights = {}
    for ticker, holding in holdings_map.items():
        price = prices.get(ticker, 0.0)
        value = holding["shares"] * price if price > 0 else holding.get("value", 0.0)
        if nav_eur > 0:
            position_weights[ticker] = (value / nav_eur) * 100.0
        else:
            position_weights[ticker] = 0.0

    # Build trade suggestions
    suggestions = []

    for ticker, signal_data in signals.items():
        signal = signal_data.get("signal", "HOLD")
        if signal == "HOLD":
            continue

        # Get strategy params if available
        saved_strategy_id = assignment_map.get(ticker)
        strategy_params = {}
        if saved_strategy_id and saved_strategy_id in saved_strategy_map:
            strategy_params = saved_strategy_map[saved_strategy_id].get("params", {})

        # Get current position weight
        current_weight = position_weights.get(ticker, 0.0)

        # Compute target delta based on sizing mode
        if sizing_mode == "step":
            trade = _compute_step_based_trade(
                ticker=ticker,
                signal=signal,
                signal_data=signal_data,
                current_weight=current_weight,
                nav_eur=nav_eur,
                price=prices.get(ticker, 0.0),
                policy=policy,
            )
        elif sizing_mode == "risk_atr":
            trade = _compute_risk_atr_trade(
                ticker=ticker,
                signal=signal,
                signal_data=signal_data,
                current_weight=current_weight,
                nav_eur=nav_eur,
                price=prices.get(ticker, 0.0),
                strategy_params=strategy_params,
                policy=policy,
                ohlcv_df=ohlcv_data.get(ticker) if ohlcv_data else None,
            )
        else:
            continue

        if trade:
            # Add stop price suggestion
            if trade["shares_delta"] != 0:
                stop_data = _compute_stop_suggestion(
                    ticker=ticker,
                    last_close=prices.get(ticker, 0.0),
                    signal=signal,
                    strategy_params=strategy_params,
                    policy=policy,
                    ohlcv_df=ohlcv_data.get(ticker) if ohlcv_data else None,
                )
                trade.update(stop_data)

            suggestions.append(trade)

    return suggestions


def _compute_step_based_trade(
    ticker: str,
    signal: str,
    signal_data: dict,
    current_weight: float,
    nav_eur: float,
    price: float,
    policy: dict,
) -> dict | None:
    """Compute step-based trade suggestion (Rule A).

    Args:
        ticker: Stock ticker
        signal: BUY or SELL
        signal_data: Signal metadata with strength/confidence
        current_weight: Current position weight (%)
        nav_eur: Portfolio NAV
        price: Current price
        policy: Policy with step sizing parameters

    Returns:
        Trade dict or None if trade should be skipped
    """
    if price <= 0 or nav_eur <= 0:
        return None

    step_pct = policy.get("signal_step_pct", 1.0)
    strong_step_pct = policy.get("signal_strong_step_pct", 2.0)
    exit_threshold_pct = policy.get("signal_exit_threshold_pct", 0.5)
    min_trade_eur = policy.get("signal_min_trade_eur", 250.0)
    max_position_pct = policy.get("max_position_pct", 10.0)

    # Determine if signal is strong
    strength = signal_data.get("strength", 1)
    is_strong = strength >= 2

    # Select step size
    step = strong_step_pct if is_strong else step_pct

    # Compute delta weight
    if signal == "BUY":
        delta_weight = step
        target_weight = current_weight + delta_weight
        # Cap by max position
        if target_weight > max_position_pct:
            delta_weight = max_position_pct - current_weight
            target_weight = max_position_pct

        if delta_weight <= 0:
            return None

        action = "INCREASE" if current_weight > 0 else "BUY"

    elif signal == "SELL":
        delta_weight = -step
        target_weight = current_weight + delta_weight

        # Check exit threshold
        if target_weight < exit_threshold_pct:
            delta_weight = -current_weight
            target_weight = 0.0
            action = "EXIT"
        else:
            action = "REDUCE"

        if delta_weight >= 0:
            return None
    else:
        return None

    # Convert to EUR and shares
    delta_value_eur = (delta_weight / 100.0) * nav_eur
    delta_shares = int(delta_value_eur / price)

    # Enforce minimum trade value
    actual_trade_value = abs(delta_shares * price)
    if actual_trade_value < min_trade_eur:
        return {
            "ticker": ticker,
            "action": action,
            "signal": signal,
            "sizing_rule": "step",
            "delta_weight_pct": 0.0,
            "delta_value_eur": 0.0,
            "delta_shares": 0,
            "skipped": True,
            "reason": f"Trade value €{actual_trade_value:.0f} < min €{min_trade_eur:.0f}",
        }

    reason = f"{signal} signal (strength={strength}), step={step:.1f}%"

    return {
        "ticker": ticker,
        "action": action,
        "signal": signal,
        "sizing_rule": "step",
        "delta_weight_pct": delta_weight,
        "delta_value_eur": delta_value_eur,
        "delta_shares": delta_shares,
        "target_weight_pct": target_weight,
        "reason": reason,
        "skipped": False,
    }


def _compute_risk_atr_trade(
    ticker: str,
    signal: str,
    signal_data: dict,
    current_weight: float,
    nav_eur: float,
    price: float,
    strategy_params: dict,
    policy: dict,
    ohlcv_df: pd.DataFrame | None,
) -> dict | None:
    """Compute risk/ATR-based trade suggestion (Rule B).

    Args:
        ticker: Stock ticker
        signal: BUY or SELL
        signal_data: Signal metadata
        current_weight: Current position weight (%)
        nav_eur: Portfolio NAV
        price: Current price
        strategy_params: Strategy parameters (may contain stop_loss_pct)
        policy: Policy with risk/ATR parameters
        ohlcv_df: OHLCV DataFrame for ATR calculation

    Returns:
        Trade dict or None if trade should be skipped
    """
    if price <= 0 or nav_eur <= 0:
        return None

    risk_pct = policy.get("signal_risk_per_trade_pct", 0.5) / 100.0
    atr_period = policy.get("signal_atr_period", 14)
    atr_mult = policy.get("signal_atr_mult", 2.0)
    stop_source = policy.get("signal_stop_source", "strategy_stop")
    min_trade_eur = policy.get("signal_min_trade_eur", 250.0)
    max_position_pct = policy.get("max_position_pct", 10.0)

    risk_eur = nav_eur * risk_pct

    # Determine stop distance
    stop_dist = None

    if stop_source == "strategy_stop" and "stop_loss_pct" in strategy_params:
        stop_dist = strategy_params["stop_loss_pct"] / 100.0
    elif ohlcv_df is not None and len(ohlcv_df) >= atr_period + 1:
        # Compute ATR-based stop
        atr = compute_atr(ohlcv_df["High"], ohlcv_df["Low"], ohlcv_df["Close"], period=atr_period)
        if atr > 0:
            atr_pct = atr / price
            stop_dist = atr_pct * atr_mult

    # Fallback: 8% conservative default
    if stop_dist is None or stop_dist <= 0:
        stop_dist = 0.08

    # Compute position value target
    position_value = risk_eur / stop_dist
    target_weight = (position_value / nav_eur) * 100.0

    # Cap by max position
    if target_weight > max_position_pct:
        target_weight = max_position_pct
        position_value = (target_weight / 100.0) * nav_eur

    delta_weight = target_weight - current_weight

    if signal == "BUY":
        if delta_weight <= 0:
            return None
        action = "INCREASE" if current_weight > 0 else "BUY"

    elif signal == "SELL":
        # For SELL, reduce to zero
        delta_weight = -current_weight
        target_weight = 0.0
        action = "EXIT"

        if delta_weight >= 0:
            return None
    else:
        return None

    # Convert to EUR and shares
    delta_value_eur = (delta_weight / 100.0) * nav_eur
    delta_shares = int(delta_value_eur / price)

    # Enforce minimum trade value
    actual_trade_value = abs(delta_shares * price)
    if actual_trade_value < min_trade_eur:
        return {
            "ticker": ticker,
            "action": action,
            "signal": signal,
            "sizing_rule": "risk_atr",
            "delta_weight_pct": 0.0,
            "delta_value_eur": 0.0,
            "delta_shares": 0,
            "skipped": True,
            "reason": f"Trade value €{actual_trade_value:.0f} < min €{min_trade_eur:.0f}",
        }

    reason = f"{signal} signal, risk={risk_pct*100:.1f}%, stop={stop_dist*100:.1f}%"

    return {
        "ticker": ticker,
        "action": action,
        "signal": signal,
        "sizing_rule": "risk_atr",
        "delta_weight_pct": delta_weight,
        "delta_value_eur": delta_value_eur,
        "delta_shares": delta_shares,
        "target_weight_pct": target_weight,
        "reason": reason,
        "skipped": False,
    }


def _compute_stop_suggestion(
    ticker: str,
    last_close: float,
    signal: str,
    strategy_params: dict,
    policy: dict,
    ohlcv_df: pd.DataFrame | None,
) -> dict:
    """Compute stop/stop-limit price suggestion based on EOD data.

    Args:
        ticker: Stock ticker
        last_close: Most recent close price
        signal: BUY or SELL
        strategy_params: Strategy parameters (may contain stop_loss_pct)
        policy: Policy with stop settings
        ohlcv_df: OHLCV DataFrame for ATR calculation

    Returns:
        Dict with stop_price, limit_price, reference_close_date
    """
    if last_close <= 0:
        return {"stop_price": None, "limit_price": None, "reference_close_date": None}

    # Only suggest stops for positions we're entering or holding (BUY)
    # For SELL/EXIT, stops are not relevant
    if signal != "BUY":
        return {"stop_price": None, "limit_price": None, "reference_close_date": None}

    stop_source = policy.get("signal_stop_source", "strategy_stop")
    atr_period = policy.get("signal_atr_period", 14)
    atr_mult = policy.get("signal_atr_mult", 2.0)
    stop_order_type = policy.get("signal_stop_order_type", "stop_limit")
    buffer_bps = policy.get("signal_stop_limit_buffer_bps", 25.0)

    # Determine stop distance
    stop_dist = None

    if stop_source == "strategy_stop" and "stop_loss_pct" in strategy_params:
        stop_dist = strategy_params["stop_loss_pct"] / 100.0
    elif ohlcv_df is not None and len(ohlcv_df) >= atr_period + 1:
        atr = compute_atr(ohlcv_df["High"], ohlcv_df["Low"], ohlcv_df["Close"], period=atr_period)
        if atr > 0:
            atr_pct = atr / last_close
            stop_dist = atr_pct * atr_mult

    # Fallback: 8% conservative default
    if stop_dist is None or stop_dist <= 0:
        stop_dist = 0.08

    # Compute stop price (for long position)
    stop_price = last_close * (1 - stop_dist)

    # Compute limit price for stop-limit orders
    limit_price = None
    if stop_order_type == "stop_limit":
        buffer = buffer_bps / 10000.0
        limit_price = stop_price * (1 - buffer)

    # Get reference date
    reference_date = None
    if ohlcv_df is not None and not ohlcv_df.empty:
        reference_date = ohlcv_df.index[-1].strftime("%Y-%m-%d") if hasattr(ohlcv_df.index[-1], "strftime") else str(ohlcv_df.index[-1])

    return {
        "stop_price": stop_price,
        "limit_price": limit_price,
        "reference_close_date": reference_date,
    }
