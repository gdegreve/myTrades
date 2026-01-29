"""Rebalance plan computation logic.

Pure Python business logic for computing rebalance plans from positions, signals,
policy targets, and market prices. NO SQL, NO Dash components - just transformation
of data structures into concrete trade recommendations.
"""

from __future__ import annotations

import json
from typing import Any


def compute_signal_trades(
    positions: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    prices: dict[str, float],
) -> list[dict[str, Any]]:
    """Convert signal directives (BUY/SELL x%) into concrete share trades.

    Args:
        positions: List of dicts with keys: ticker, shares, avg_cost, cost_basis
        signals: List of dicts with keys: ticker, signal (BUY/SELL/HOLD), reason, meta_json (optional)
        prices: Dict of {ticker: latest_close_price}

    Returns:
        List of trade dicts: {
            ticker: str,
            layer: "Signal",
            signal: str (BUY/SELL),
            shares_delta: int (positive for BUY, negative for SELL),
            price: float,
            estimated_eur: float (negative for sells, positive for buys),
            reason: str
        }

    Logic:
        - For BUY x%: calculate shares to buy based on current position value and percentage
        - For SELL x%: calculate shares to sell (negative delta)
        - Round to integer shares (BUY rounds down, SELL rounds up to not over-sell)
        - HOLD signals produce no trade
        - If signal has no percentage in meta_json, defaults to 10%
    """
    trades = []

    # Build position lookup
    position_map = {p["ticker"]: p for p in positions}

    for sig in signals:
        ticker = sig["ticker"]
        signal_type = sig["signal"].upper()
        reason = sig.get("reason", "")

        # Skip HOLD signals
        if signal_type == "HOLD":
            continue

        # Parse percentage from meta_json
        percentage = 10.0  # Default
        meta_json = sig.get("meta_json")
        if meta_json:
            try:
                meta = json.loads(meta_json) if isinstance(meta_json, str) else meta_json
                percentage = float(meta.get("percentage", 10.0))
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Get current position and price
        position = position_map.get(ticker, {"shares": 0.0, "cost_basis": 0.0})
        price = prices.get(ticker)

        if price is None or price <= 0:
            # Skip if no valid price
            continue

        current_shares = position["shares"]
        current_value = current_shares * price

        if signal_type == "BUY":
            # Calculate shares to buy based on percentage of current position value
            # If no position, use a base value (e.g., 1000 EUR) for the calculation
            base_value = current_value if current_value > 0 else 1000.0
            target_buy_value = base_value * (percentage / 100.0)
            target_shares = target_buy_value / price
            shares_delta = int(target_shares)  # Round down for buys

            if shares_delta <= 0:
                continue

            estimated_eur = shares_delta * price

            trades.append({
                "ticker": ticker,
                "layer": "Signal",
                "signal": "BUY",
                "shares_delta": shares_delta,
                "price": price,
                "estimated_eur": estimated_eur,
                "reason": reason,
            })

        elif signal_type == "SELL":
            # Calculate shares to sell based on percentage of current position
            if current_shares <= 0:
                continue  # Can't sell if no position

            target_shares = current_shares * (percentage / 100.0)
            shares_delta = -int(target_shares + 0.9999)  # Round up for sells (ceiling)

            # Ensure we don't sell more than we have
            if abs(shares_delta) > current_shares:
                shares_delta = -int(current_shares)

            if shares_delta == 0:
                continue

            estimated_eur = shares_delta * price  # Will be negative

            trades.append({
                "ticker": ticker,
                "layer": "Signal",
                "signal": "SELL",
                "shares_delta": shares_delta,
                "price": price,
                "estimated_eur": estimated_eur,
                "reason": reason,
            })

    return trades


def compute_post_signal_state(
    positions: list[dict[str, Any]],
    signal_trades: list[dict[str, Any]],
    cash: float,
    prices: dict[str, float],
    ticker_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Calculate portfolio state after applying signal trades.

    Args:
        positions: Current positions (ticker, shares, avg_cost, cost_basis)
        signal_trades: Trades from compute_signal_trades()
        cash: Current cash balance
        prices: Dict of {ticker: price}
        ticker_metadata: Optional dict of {ticker: {sector, region}}

    Returns:
        dict with keys:
            - positions: list (updated positions after signal trades)
            - cash: float (cash after signal trades)
            - sector_allocations: dict {sector: pct}
            - region_allocations: dict {region: pct}
            - total_value: float (sum of holdings + cash)
    """
    if ticker_metadata is None:
        ticker_metadata = {}

    # Clone positions to avoid mutation
    position_map = {p["ticker"]: dict(p) for p in positions}

    # Apply signal trades
    updated_cash = cash
    for trade in signal_trades:
        ticker = trade["ticker"]
        shares_delta = trade["shares_delta"]
        price = trade["price"]

        # Update position
        if ticker not in position_map:
            position_map[ticker] = {
                "ticker": ticker,
                "shares": 0.0,
                "avg_cost": 0.0,
                "cost_basis": 0.0,
            }

        pos = position_map[ticker]

        if shares_delta > 0:  # BUY
            # Add shares and update cost basis
            new_cost = shares_delta * price
            total_cost = pos["cost_basis"] + new_cost
            total_shares = pos["shares"] + shares_delta

            pos["shares"] = total_shares
            pos["cost_basis"] = total_cost
            pos["avg_cost"] = total_cost / total_shares if total_shares > 0 else 0.0

            updated_cash -= new_cost

        elif shares_delta < 0:  # SELL
            # Reduce shares proportionally
            sell_shares = abs(shares_delta)
            if pos["shares"] > 0:
                reduction_ratio = sell_shares / pos["shares"]
                pos["cost_basis"] *= (1 - reduction_ratio)
                pos["shares"] -= sell_shares

                if pos["shares"] > 0:
                    pos["avg_cost"] = pos["cost_basis"] / pos["shares"]
                else:
                    pos["avg_cost"] = 0.0

            updated_cash += abs(shares_delta) * price

    # Filter out zero positions
    updated_positions = [
        p for p in position_map.values()
        if p["shares"] > 0.0001
    ]

    # Compute allocations
    sector_values = {}
    region_values = {}
    total_holdings_value = 0.0

    for pos in updated_positions:
        ticker = pos["ticker"]
        price = prices.get(ticker, pos["avg_cost"])
        position_value = pos["shares"] * price
        total_holdings_value += position_value

        # Get metadata
        meta = ticker_metadata.get(ticker, {})
        sector = meta.get("sector", "Unknown")
        region = meta.get("region", "Unknown")

        sector_values[sector] = sector_values.get(sector, 0.0) + position_value
        region_values[region] = region_values.get(region, 0.0) + position_value

    total_value = total_holdings_value + updated_cash

    # Convert to percentages
    sector_allocations = {}
    region_allocations = {}

    if total_value > 0:
        sector_allocations = {
            sector: (value / total_value) * 100.0
            for sector, value in sector_values.items()
        }
        region_allocations = {
            region: (value / total_value) * 100.0
            for region, value in region_values.items()
        }

    return {
        "positions": updated_positions,
        "cash": updated_cash,
        "sector_allocations": sector_allocations,
        "region_allocations": region_allocations,
        "total_value": total_value,
    }


def compute_drift(
    allocations: dict[str, float],
    policy_targets: list[dict[str, Any]],
    dimension: str = "Sector",
) -> list[dict[str, Any]]:
    """Calculate drift for each dimension (sector/region/cash).

    Args:
        allocations: Dict of {bucket: current_pct}
        policy_targets: List of dicts with keys: bucket (or sector/region), target_pct, min_pct, max_pct
        dimension: Dimension label ("Sector", "Region", "Cash")

    Returns:
        List of drift dicts: {
            dimension: str,
            bucket: str,
            target_pct: float,
            current_pct: float,
            drift_pct: float (current - target),
            status: str (OK/WARN/BREACH),
            action: str (Increase/Reduce/None)
        }

    Status logic:
        - OK: current within [min, max]
        - WARN: current within 1% of min or max
        - BREACH: current outside [min, max]
    """
    drift_list = []

    for target_spec in policy_targets:
        # Handle different key names (sector/region/bucket)
        bucket = target_spec.get("sector") or target_spec.get("region") or target_spec.get("bucket")
        target_pct = target_spec.get("target_pct", 0.0)
        min_pct = target_spec.get("min_pct")
        max_pct = target_spec.get("max_pct")

        if bucket is None:
            continue

        current_pct = allocations.get(bucket, 0.0)
        drift_pct = current_pct - target_pct

        # Determine status and action
        status = "OK"
        action = "None"

        if min_pct is not None and current_pct < min_pct:
            status = "BREACH"
            action = "Increase"
        elif max_pct is not None and current_pct > max_pct:
            status = "BREACH"
            action = "Reduce"
        elif min_pct is not None and abs(current_pct - min_pct) <= 1.0:
            status = "WARN"
            action = "Increase" if current_pct < target_pct else "None"
        elif max_pct is not None and abs(current_pct - max_pct) <= 1.0:
            status = "WARN"
            action = "Reduce" if current_pct > target_pct else "None"

        drift_list.append({
            "dimension": dimension,
            "bucket": bucket,
            "target_pct": target_pct,
            "current_pct": current_pct,
            "drift_pct": drift_pct,
            "status": status,
            "action": action,
        })

    return drift_list


def compute_compensation_trades(
    post_signal_state: dict[str, Any],
    policy_snapshot: dict[str, Any],
    prices: dict[str, float],
    ticker_metadata: dict[str, dict[str, Any]],
    available_tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Generate compensation trades to fix policy breaches AFTER signals applied.

    Args:
        post_signal_state: Output from compute_post_signal_state()
        policy_snapshot: Full policy with sector/region targets and cash policy
        prices: Dict of {ticker: price}
        ticker_metadata: Dict of {ticker: {sector, region}}
        available_tickers: Optional list of tickers with HOLD signal (preferred for rebalancing)

    Returns:
        List of trade dicts: {
            ticker: str,
            layer: "Rebalance",
            signal: "REBAL",
            shares_delta: int,
            price: float,
            estimated_eur: float,
            reason: str
        }

    Logic:
        - Fix cash breaches first (sell to build cash if below min, buy if above max)
        - Then fix sector breaches (sell overweight, buy underweight)
        - Then fix region breaches
        - Prefer HOLD-signal tickers for rebalancing
        - Integer shares only
        - Don't exceed available cash for buys
    """
    trades = []

    if available_tickers is None:
        available_tickers = list(prices.keys())

    positions = post_signal_state["positions"]
    cash = post_signal_state["cash"]
    total_value = post_signal_state["total_value"]

    if total_value <= 0:
        return trades

    # Get policy constraints
    policy = policy_snapshot.get("policy", {})
    cash_min_pct = policy.get("cash_min_pct", 0.0)
    cash_max_pct = policy.get("cash_max_pct", 100.0)

    current_cash_pct = (cash / total_value) * 100.0

    # Fix cash breaches first
    if current_cash_pct < cash_min_pct:
        # Need to raise cash by selling
        target_cash = (cash_min_pct / 100.0) * total_value
        needed_cash = target_cash - cash

        # Find positions to sell (prefer HOLD tickers)
        position_map = {p["ticker"]: p for p in positions}
        sell_candidates = [
            (ticker, position_map[ticker])
            for ticker in available_tickers
            if ticker in position_map
        ]

        # Sell proportionally from candidates
        for ticker, pos in sell_candidates:
            if needed_cash <= 0:
                break

            price = prices.get(ticker)
            if not price or price <= 0:
                continue

            # Sell shares to raise needed cash
            shares_to_sell = int(needed_cash / price + 0.9999)  # Round up
            shares_to_sell = min(shares_to_sell, int(pos["shares"]))

            if shares_to_sell > 0:
                estimated_eur = -shares_to_sell * price
                trades.append({
                    "ticker": ticker,
                    "layer": "Rebalance",
                    "signal": "REBAL",
                    "shares_delta": -shares_to_sell,
                    "price": price,
                    "estimated_eur": estimated_eur,
                    "reason": f"Raise cash to meet {cash_min_pct:.1f}% minimum",
                })
                needed_cash -= shares_to_sell * price
                cash += shares_to_sell * price

    elif current_cash_pct > cash_max_pct:
        # Too much cash, need to invest
        target_cash = (cash_max_pct / 100.0) * total_value
        excess_cash = cash - target_cash

        # Find tickers to buy (prefer HOLD tickers)
        buy_candidates = [
            ticker for ticker in available_tickers
            if ticker in prices and prices[ticker] > 0
        ]

        if buy_candidates and excess_cash > 0:
            # Distribute excess cash equally among candidates
            per_ticker = excess_cash / len(buy_candidates)

            for ticker in buy_candidates:
                price = prices.get(ticker)
                if not price or price <= 0:
                    continue

                shares_to_buy = int(per_ticker / price)  # Round down

                if shares_to_buy > 0:
                    estimated_eur = shares_to_buy * price
                    trades.append({
                        "ticker": ticker,
                        "layer": "Rebalance",
                        "signal": "REBAL",
                        "shares_delta": shares_to_buy,
                        "price": price,
                        "estimated_eur": estimated_eur,
                        "reason": f"Deploy cash below {cash_max_pct:.1f}% maximum",
                    })
                    cash -= shares_to_buy * price

    # TODO: Sector and region rebalancing would go here
    # For now, we only fix cash breaches

    return trades


def compute_cash_preview(
    starting_cash: float,
    trades: list[dict[str, Any]],
    policy_snapshot: dict[str, Any] | None = None,
    total_portfolio_value: float | None = None,
) -> dict[str, Any]:
    """Calculate cash impact of proposed trades.

    Args:
        starting_cash: Initial cash balance
        trades: List of trade dicts with estimated_eur field
        policy_snapshot: Optional policy snapshot for status evaluation
        total_portfolio_value: Optional total portfolio value for percentage calculation

    Returns:
        dict with keys:
            - starting_cash: float
            - net_impact: float (sum of all trade impacts)
            - ending_cash: float
            - ending_cash_pct: float (percentage of total value, if provided)
            - status: str (OK/WARN/BREACH if policy provided, otherwise None)
    """
    net_impact = sum(trade.get("estimated_eur", 0.0) for trade in trades)
    ending_cash = starting_cash - net_impact  # Buys are positive impact, sells are negative

    ending_cash_pct = None
    if total_portfolio_value and total_portfolio_value > 0:
        ending_cash_pct = (ending_cash / total_portfolio_value) * 100.0

    status = None
    if policy_snapshot and ending_cash_pct is not None:
        policy = policy_snapshot.get("policy", {})
        cash_min_pct = policy.get("cash_min_pct", 0.0)
        cash_max_pct = policy.get("cash_max_pct", 100.0)

        if ending_cash_pct < cash_min_pct:
            status = "BREACH"
        elif ending_cash_pct > cash_max_pct:
            status = "BREACH"
        elif abs(ending_cash_pct - cash_min_pct) <= 1.0:
            status = "WARN"
        elif abs(ending_cash_pct - cash_max_pct) <= 1.0:
            status = "WARN"
        else:
            status = "OK"

    return {
        "starting_cash": starting_cash,
        "net_impact": net_impact,
        "ending_cash": ending_cash,
        "ending_cash_pct": ending_cash_pct,
        "status": status,
    }


def compute_full_rebalance_plan(
    positions: list[dict[str, Any]],
    cash: float,
    policy_snapshot: dict[str, Any],
    signals: list[dict[str, Any]],
    prices: dict[str, float],
    ticker_metadata: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Main entry point that combines all rebalance computation steps.

    Args:
        positions: Current holdings (ticker, shares, avg_cost, cost_basis)
        cash: Current cash balance
        policy_snapshot: From policy_repo.load_policy_snapshot()
        signals: From rebalance_repo.get_signals_for_portfolio()
        prices: Latest EOD prices {ticker: price}
        ticker_metadata: Dict of {ticker: {sector, region}}

    Returns:
        dict with keys:
            - signal_trades: list (trades from signals)
            - compensation_trades: list (trades to fix policy breaches)
            - all_trades: list (signal + compensation combined)
            - drift_before: list (drift before any trades)
            - drift_after: list (drift after all trades)
            - cash_preview_signals_only: dict (cash impact of signals only)
            - cash_preview_full: dict (cash impact of all trades)
            - summary: dict with aggregated metrics
    """
    # Compute initial state
    position_map = {p["ticker"]: p for p in positions}
    sector_values = {}
    region_values = {}
    total_holdings_value = 0.0

    for pos in positions:
        ticker = pos["ticker"]
        price = prices.get(ticker, pos["avg_cost"])
        position_value = pos["shares"] * price
        total_holdings_value += position_value

        meta = ticker_metadata.get(ticker, {})
        sector = meta.get("sector", "Unknown")
        region = meta.get("region", "Unknown")

        sector_values[sector] = sector_values.get(sector, 0.0) + position_value
        region_values[region] = region_values.get(region, 0.0) + position_value

    total_value_before = total_holdings_value + cash

    initial_sector_allocations = {}
    initial_region_allocations = {}

    if total_value_before > 0:
        initial_sector_allocations = {
            s: (v / total_value_before) * 100.0
            for s, v in sector_values.items()
        }
        initial_region_allocations = {
            r: (v / total_value_before) * 100.0
            for r, v in region_values.items()
        }

    # Compute drift before any trades
    sector_targets = policy_snapshot.get("sector_targets", [])
    region_targets = policy_snapshot.get("region_targets", [])

    drift_before = []
    drift_before.extend(compute_drift(initial_sector_allocations, sector_targets, dimension="Sector"))
    drift_before.extend(compute_drift(initial_region_allocations, region_targets, dimension="Region"))

    # Add cash drift
    policy = policy_snapshot.get("policy", {})
    cash_target_pct = policy.get("cash_target_pct", 5.0)
    cash_min_pct = policy.get("cash_min_pct", 0.0)
    cash_max_pct = policy.get("cash_max_pct", 100.0)
    current_cash_pct = (cash / total_value_before) * 100.0 if total_value_before > 0 else 0.0

    cash_status = "OK"
    cash_action = "None"
    if current_cash_pct < cash_min_pct:
        cash_status = "BREACH"
        cash_action = "Increase"
    elif current_cash_pct > cash_max_pct:
        cash_status = "BREACH"
        cash_action = "Reduce"

    drift_before.append({
        "dimension": "Cash",
        "bucket": "Cash",
        "target_pct": cash_target_pct,
        "current_pct": current_cash_pct,
        "drift_pct": current_cash_pct - cash_target_pct,
        "status": cash_status,
        "action": cash_action,
    })

    # Step 1: Compute signal trades
    signal_trades = compute_signal_trades(positions, signals, prices)

    # Step 2: Compute state after signal trades
    post_signal_state = compute_post_signal_state(
        positions, signal_trades, cash, prices, ticker_metadata
    )

    # Step 3: Identify HOLD tickers for rebalancing
    hold_tickers = [
        sig["ticker"] for sig in signals
        if sig["signal"].upper() == "HOLD"
    ]

    # Step 4: Compute compensation trades
    compensation_trades = compute_compensation_trades(
        post_signal_state,
        policy_snapshot,
        prices,
        ticker_metadata,
        available_tickers=hold_tickers if hold_tickers else None,
    )

    # Combine all trades
    all_trades = signal_trades + compensation_trades

    # Step 5: Compute final state after all trades
    final_state = compute_post_signal_state(
        post_signal_state["positions"],
        compensation_trades,
        post_signal_state["cash"],
        prices,
        ticker_metadata,
    )

    # Compute drift after all trades
    drift_after = []
    drift_after.extend(compute_drift(final_state["sector_allocations"], sector_targets, dimension="Sector"))
    drift_after.extend(compute_drift(final_state["region_allocations"], region_targets, dimension="Region"))

    final_cash_pct = (final_state["cash"] / final_state["total_value"]) * 100.0 if final_state["total_value"] > 0 else 0.0
    final_cash_status = "OK"
    final_cash_action = "None"
    if final_cash_pct < cash_min_pct:
        final_cash_status = "BREACH"
        final_cash_action = "Increase"
    elif final_cash_pct > cash_max_pct:
        final_cash_status = "BREACH"
        final_cash_action = "Reduce"

    drift_after.append({
        "dimension": "Cash",
        "bucket": "Cash",
        "target_pct": cash_target_pct,
        "current_pct": final_cash_pct,
        "drift_pct": final_cash_pct - cash_target_pct,
        "status": final_cash_status,
        "action": final_cash_action,
    })

    # Compute cash previews
    cash_preview_signals_only = compute_cash_preview(
        cash, signal_trades, policy_snapshot, total_value_before
    )

    cash_preview_full = compute_cash_preview(
        cash, all_trades, policy_snapshot, total_value_before
    )

    # Compute summary
    sector_breaches_before = sum(1 for d in drift_before if d.get("status") == "BREACH" and d["bucket"] != "Cash")
    region_breaches_before = 0  # We'd need to distinguish sector vs region in drift_before
    sector_breaches_after = sum(1 for d in drift_after if d.get("status") == "BREACH" and d["bucket"] != "Cash")

    net_eur_impact = sum(t.get("estimated_eur", 0.0) for t in all_trades)

    summary = {
        "sector_breaches": sector_breaches_after,
        "region_breaches": 0,  # Placeholder
        "cash_status": final_cash_status,
        "total_trades": len(all_trades),
        "net_eur_impact": net_eur_impact,
    }

    return {
        "signal_trades": signal_trades,
        "compensation_trades": compensation_trades,
        "all_trades": all_trades,
        "drift_before": drift_before,
        "drift_after": drift_after,
        "cash_preview_signals_only": cash_preview_signals_only,
        "cash_preview_full": cash_preview_full,
        "summary": summary,
    }
