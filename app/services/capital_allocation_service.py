"""Capital Allocation Score (CAS) service.

Computes a deterministic, explainable score (0-100) for portfolio and watchlist tickers
based on fundamentals, trend alignment, portfolio fit, position risk, and cash bonus.
"""
from __future__ import annotations

from typing import Any


def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, x))


def compute_cas(
    ticker: str,
    signal: str | None = None,
    is_position: bool = False,
    shares: float = 0.0,
    position_value: float = 0.0,
    total_portfolio_value: float = 0.0,
    fundamental_score: float | None = None,
    policy: dict[str, Any] | None = None,
    cash_pct: float | None = None,
) -> dict[str, Any]:
    """
    Compute Capital Allocation Score and component breakdown.

    Args:
        ticker: Ticker symbol
        signal: Signal type (BUY, SELL, HOLD, DATA, None)
        is_position: True if ticker is held, False if watchlist-only
        shares: Number of shares held (0 if watchlist)
        position_value: Market value of position
        total_portfolio_value: Total portfolio value (positions + cash)
        fundamental_score: Fundamental score from benchmarks (0-100, or None)
        policy: Portfolio policy dict with max_position_pct, cash_target_pct, etc.
        cash_pct: Current cash as % of portfolio

    Returns:
        Dict with:
            - cas: float (0-100)
            - verdict: str (PRIORITY, HOLD, WEAK, AVOID)
            - components: dict with breakdown of each component
    """
    if policy is None:
        policy = {}
    if cash_pct is None:
        cash_pct = 0.0

    # =====================================================================
    # Component 1: Fundamental Score (0-100)
    # =====================================================================
    if fundamental_score is not None:
        fundamental = clamp(fundamental_score, 0, 100)
    else:
        fundamental = 50.0  # Neutral default

    # =====================================================================
    # Component 2: Trend & Signal Alignment (0-100)
    # =====================================================================
    signal_map = {
        "BUY": 100,
        "HOLD": 50,
        "SELL": 0,
        "DATA": 25,
        None: 50,
    }
    trend_signal = clamp(signal_map.get(signal, 50), 0, 100)

    # =====================================================================
    # Component 3: Portfolio Fit (0-100)
    # =====================================================================
    portfolio_fit = 100.0

    # Check max position constraint
    max_position_pct = policy.get("max_position_pct")
    if max_position_pct and max_position_pct > 0 and total_portfolio_value > 0:
        position_pct = (position_value / total_portfolio_value) * 100
        if position_pct > max_position_pct:
            portfolio_fit = 0.0

    # Check cash constraint (if cash is below target, slight penalty)
    cash_target_pct = policy.get("cash_target_pct")
    if cash_target_pct and cash_target_pct > 0 and cash_pct < cash_target_pct:
        portfolio_fit -= 10.0

    portfolio_fit = clamp(portfolio_fit, 0, 100)

    # =====================================================================
    # Component 4: Position Risk (0-100)
    # =====================================================================
    if not is_position:
        # Watchlist: no position risk yet
        position_risk = 100.0
    else:
        position_pct = (position_value / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
        max_pos = policy.get("max_position_pct", 10.0)

        if max_pos > 0:
            threshold_half = 0.5 * max_pos
            if position_pct <= threshold_half:
                position_risk = 80.0
            elif position_pct <= max_pos:
                position_risk = 60.0
            else:
                position_risk = 0.0
        else:
            # No max_position_pct defined; use defaults
            if position_pct < 5:
                position_risk = 80.0
            elif position_pct <= 10:
                position_risk = 60.0
            else:
                position_risk = 40.0

    position_risk = clamp(position_risk, 0, 100)

    # =====================================================================
    # Component 5: Cash Bonus (0-100)
    # =====================================================================
    cash_bonus = 0.0
    cash_target_pct = policy.get("cash_target_pct", 0.0)
    if cash_pct > cash_target_pct:
        cash_bonus = min((cash_pct - cash_target_pct) * 5, 100)

    cash_bonus = clamp(cash_bonus, 0, 100)

    # =====================================================================
    # Weighted Sum
    # =====================================================================
    cas = (
        0.35 * fundamental
        + 0.25 * trend_signal
        + 0.20 * portfolio_fit
        + 0.15 * position_risk
        + 0.05 * cash_bonus
    )
    cas = clamp(cas, 0, 100)

    # =====================================================================
    # Verdict
    # =====================================================================
    if cas >= 75:
        verdict = "PRIORITY"
    elif cas >= 60:
        verdict = "HOLD"
    elif cas >= 40:
        verdict = "WEAK"
    else:
        verdict = "AVOID"

    return {
        "cas": cas,
        "verdict": verdict,
        "components": {
            "fundamental": fundamental,
            "trend_signal": trend_signal,
            "portfolio_fit": portfolio_fit,
            "position_risk": position_risk,
            "cash_bonus": cash_bonus,
        },
    }


def compute_cas_for_rows(
    rows: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    prices: dict[str, float],
    cash_balance: float,
    policy: dict[str, Any] | None = None,
    fundamentals_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Add CAS and verdict to a list of signal rows.

    Args:
        rows: List of signal row dicts (must have 'ticker' and 'signal' keys)
        positions: List of position dicts (must have 'ticker', 'shares', 'avg_cost')
        prices: Dict of {ticker: price}
        cash_balance: Cash balance in EUR
        policy: Portfolio policy dict
        fundamentals_map: Dict of {ticker: fundamental_score} or None

    Returns:
        Updated rows list with 'cas' and 'cas_verdict' keys added
    """
    if policy is None:
        policy = {}
    if fundamentals_map is None:
        fundamentals_map = {}

    # Calculate total portfolio value
    position_dict = {p["ticker"]: p for p in positions}
    total_position_value = sum(
        (position_dict.get(t, {}).get("shares", 0) or 0) * (prices.get(t, 0) or 0)
        for t in position_dict.keys()
    )
    total_portfolio_value = total_position_value + cash_balance
    if total_portfolio_value <= 0:
        total_portfolio_value = 1.0  # Avoid division by zero

    cash_pct = (cash_balance / total_portfolio_value) * 100 if total_portfolio_value > 0 else 0

    # Update each row
    updated_rows = []
    for row in rows:
        ticker = row.get("ticker")
        signal = row.get("signal")

        # Find position data
        pos = position_dict.get(ticker)
        is_position = pos is not None
        shares = (pos.get("shares") or 0) if pos else 0
        price = prices.get(ticker, 0) or 0
        position_value = shares * price

        # Get fundamental score
        fundamental_score = fundamentals_map.get(ticker)

        # Compute CAS
        cas_result = compute_cas(
            ticker=ticker,
            signal=signal,
            is_position=is_position,
            shares=shares,
            position_value=position_value,
            total_portfolio_value=total_portfolio_value,
            fundamental_score=fundamental_score,
            policy=policy,
            cash_pct=cash_pct,
        )

        # Add to row
        row_copy = dict(row)
        row_copy["cas"] = cas_result["cas"]
        row_copy["cas_verdict"] = cas_result["verdict"]

        updated_rows.append(row_copy)

    return updated_rows
