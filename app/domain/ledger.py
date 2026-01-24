"""Ledger-based computation logic.

Pure Python business logic for computing portfolio state from transaction ledger.
No SQL, no external dependencies - just transformation of ledger entries into
derived views (positions, cash balance, P&L).
"""

from __future__ import annotations
from typing import Any


def compute_cash_balance(cash_movements: list[dict[str, Any]], trades: list[dict[str, Any]]) -> float:
    """Compute current cash balance from ledger entries.

    Args:
        cash_movements: List of cash deposits/withdrawals with cash_type and amount_eur
        trades: List of stock trades with transaction_type, shares, price_eur, commission

    Returns:
        Net cash balance in EUR

    Logic:
        - Start with 0
        - Add all 'credit' (deposits)
        - Subtract all 'debit' (withdrawals)
        - Subtract cash used in 'buy' trades (shares * price_eur + commission)
        - Add cash received from 'sell' trades (shares * price_eur - commission)
    """
    balance = 0.0

    # Process cash movements
    for movement in cash_movements:
        if movement["cash_type"] == "credit":
            balance += movement["amount_eur"]
        elif movement["cash_type"] == "debit":
            balance -= movement["amount_eur"]

    # Process trades (cash impact)
    for trade in trades:
        price_eur = trade.get("price_eur") or 0.0
        shares = trade.get("shares") or 0.0
        commission = trade.get("commission") or 0.0

        if trade["transaction_type"] == "buy":
            balance -= (shares * price_eur + commission)
        elif trade["transaction_type"] == "sell":
            balance += (shares * price_eur - commission)

    return balance


def compute_positions(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute current positions from trade ledger using FIFO/average cost.

    Args:
        trades: List of trades ordered chronologically (ASC by date, id)

    Returns:
        List of position dicts with:
        - ticker: str
        - shares: float (current quantity held)
        - avg_cost: float (average cost per share in EUR, including commissions)
        - cost_basis: float (total capital deployed for this position)

    Logic:
        - Track cumulative shares per ticker
        - Compute weighted average cost including commissions
        - Buy: add shares, update avg cost
        - Sell: reduce shares, maintain avg cost (realized P&L not tracked here)
        - Filter out positions with zero or negative shares
    """
    positions_map: dict[str, dict[str, float]] = {}

    for trade in trades:
        ticker = trade["ticker"]
        transaction_type = trade["transaction_type"]
        shares = trade.get("shares") or 0.0
        price_eur = trade.get("price_eur") or 0.0
        commission = trade.get("commission") or 0.0

        if ticker not in positions_map:
            positions_map[ticker] = {"shares": 0.0, "total_cost": 0.0}

        pos = positions_map[ticker]

        if transaction_type == "buy":
            # Add shares and update total cost
            new_cost = shares * price_eur + commission
            pos["total_cost"] += new_cost
            pos["shares"] += shares

        elif transaction_type == "sell":
            # Reduce shares, keep total_cost proportional
            # (Realized P&L would be tracked separately)
            if pos["shares"] > 0:
                # Reduce cost basis proportionally
                reduction_ratio = shares / pos["shares"]
                pos["total_cost"] *= (1 - reduction_ratio)
                pos["shares"] -= shares

    # Build output list, filter zero/negative positions
    result = []
    for ticker, pos in positions_map.items():
        if pos["shares"] > 0.0001:  # Avoid floating point dust
            avg_cost = pos["total_cost"] / pos["shares"] if pos["shares"] > 0 else 0.0
            result.append({
                "ticker": ticker,
                "shares": pos["shares"],
                "avg_cost": avg_cost,
                "cost_basis": pos["total_cost"],
            })

    # Sort by ticker for consistency
    result.sort(key=lambda x: x["ticker"])
    return result


def compute_realized_pnl(trades: list[dict[str, Any]]) -> float:
    """Compute realized P&L from sell transactions.

    LIMITATION: Requires tracking cost basis per sell. Current implementation
    is a placeholder - we'd need FIFO lot tracking or average cost tracking
    at sell time to compute this accurately.

    For now, returns 0.0 as placeholder.
    """
    # TODO: Implement FIFO lot tracking for accurate realized P&L
    # Would need to match each sell with specific buy lots
    return 0.0


def compute_invested_amount(positions: list[dict[str, Any]]) -> float:
    """Compute total invested amount (cost basis) from current positions.

    Args:
        positions: List from compute_positions() with cost_basis field

    Returns:
        Sum of all cost_basis values (total capital currently deployed)
    """
    return sum(pos["cost_basis"] for pos in positions)


def check_data_completeness(positions: list[dict[str, Any]], ticker_sectors: dict[str, str]) -> dict[str, Any]:
    """Check for missing data in positions.

    Args:
        positions: Current positions from compute_positions()
        ticker_sectors: Mapping of ticker -> sector from DB

    Returns:
        Dict with:
        - missing_sectors: int (count of tickers without sector mapping)
        - missing_sectors_tickers: list[str] (tickers missing sector)
        - has_prices: bool (always False for now, future feature)
    """
    missing_sectors_tickers = []

    for pos in positions:
        ticker = pos["ticker"]
        sector = ticker_sectors.get(ticker, "")
        if not sector:
            missing_sectors_tickers.append(ticker)

    return {
        "missing_sectors": len(missing_sectors_tickers),
        "missing_sectors_tickers": missing_sectors_tickers,
        "has_prices": False,  # Placeholder for future price integration
    }


def validate_cash_transaction(
    cash_type: str,
    amount: float | None,
    current_balance: float,
    date: str | None,
) -> tuple[bool, str]:
    """Validate cash transaction inputs.

    Args:
        cash_type: 'credit' or 'debit'
        amount: Amount in EUR (or None)
        current_balance: Current cash balance
        date: Transaction date string (or None)

    Returns:
        (is_valid, error_message) tuple
        - is_valid: True if validation passes
        - error_message: Empty string if valid, otherwise specific error
    """
    if amount is None or amount <= 0:
        return False, "Amount must be greater than zero"

    if not date:
        return False, "Date is required"

    if cash_type == "debit" and amount > current_balance:
        return False, f"Insufficient cash: balance is €{current_balance:,.2f}, cannot withdraw €{amount:,.2f}"

    return True, ""


def validate_trade(
    transaction_type: str,
    ticker: str | None,
    shares: float | None,
    price: float | None,
    commission: float | None,
    current_balance: float,
    current_positions: list[dict[str, Any]],
    date: str | None,
) -> tuple[bool, str]:
    """Validate trade transaction inputs.

    Args:
        transaction_type: 'buy' or 'sell'
        ticker: Stock ticker symbol (or None)
        shares: Number of shares (or None)
        price: Price per share in EUR (or None)
        commission: Commission in EUR (or None, defaults to 0)
        current_balance: Current cash balance
        current_positions: List of current positions from compute_positions()
        date: Transaction date string (or None)

    Returns:
        (is_valid, error_message) tuple
        - is_valid: True if validation passes
        - error_message: Empty string if valid, otherwise specific error
    """
    if not ticker or not ticker.strip():
        return False, "Ticker is required"

    if shares is None or shares <= 0:
        return False, "Quantity must be greater than zero"

    if price is None or price <= 0:
        return False, "Price must be greater than zero"

    if commission is None or commission < 0:
        return False, "Commission cannot be negative"

    if not date:
        return False, "Date is required"

    commission = commission or 0.0

    if transaction_type == "buy":
        required_cash = shares * price + commission
        if required_cash > current_balance:
            return False, f"Insufficient cash: balance is €{current_balance:,.2f}, required €{required_cash:,.2f}"

    elif transaction_type == "sell":
        # Check if we have enough shares
        ticker_upper = ticker.upper()
        position = next((p for p in current_positions if p["ticker"] == ticker_upper), None)

        if not position:
            return False, f"No position in {ticker_upper} to sell"

        if shares > position["shares"]:
            return False, f"Insufficient shares: have {position['shares']:.4f}, trying to sell {shares:.4f}"

    return True, ""
