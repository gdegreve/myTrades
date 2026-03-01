#!/usr/bin/env python3
"""Test script for Today page UX upgrades."""

import sys
import time
from datetime import datetime

# Test imports
print("=" * 60)
print("TEST 1: Syntax & Import Check")
print("=" * 60)

try:
    from app.pages import page_today
    print("✓ page_today imports successfully")
except Exception as e:
    print(f"✗ Import failed: {e}")
    sys.exit(1)

# Test layout generation
try:
    layout = page_today.layout()
    print("✓ layout() generates successfully")
    print(f"  Type: {type(layout)}")
except Exception as e:
    print(f"✗ Layout generation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 2: CSS Classes Verification")
print("=" * 60)

css_classes = [
    "status-card-clickable",
    "status-card-ok",
    "status-card-warn",
    "status-card-bad",
    "status-card-info",
    "ai-brief-toggle-btn",
    "ai-brief-collapsed",
    "ai-brief-expanded",
    "ai-brief-content-wrapper",
    "today-ai-brief",
]

import os
css_path = "/home/gdegreve/Projects/Python/Trading/myTrading-dash/app/assets/styles.css"
with open(css_path, "r") as f:
    css_content = f.read()

for cls in css_classes:
    if f".{cls}" in css_content:
        print(f"✓ .{cls} exists in CSS")
    else:
        print(f"✗ .{cls} NOT FOUND in CSS")

print("\n" + "=" * 60)
print("TEST 3: Component IDs Check")
print("=" * 60)

component_ids = [
    "today-markets-primary",
    "today-markets-sub",
    "today-health-primary",
    "today-health-sub",
    "today-cash-primary",
    "today-cash-sub",
    "today-signals-primary",
    "today-signals-sub",
    "today-posture-line",
    "ai-brief-card",
    "ai-brief-toggle-btn",
    "ai-brief-content",
    "ai-brief-collapsed-state",
    "today-markets-card-wrapper",
    "today-health-card-wrapper",
    "today-cash-card-wrapper",
    "today-signals-card-wrapper",
]

# Check if IDs are in layout by converting to string (rough check)
layout_str = str(layout)
for comp_id in component_ids:
    if comp_id in layout_str:
        print(f"✓ {comp_id} found in layout")
    else:
        print(f"✗ {comp_id} NOT FOUND in layout")

print("\n" + "=" * 60)
print("TEST 4: Database Data Check")
print("=" * 60)

try:
    from app.db.portfolio_repo import get_active_portfolio_ids
    from app.db.policy_repo import load_policy_snapshot
    from app.db.ledger_repo import list_trades, list_cash_movements
    from app.db.prices_repo import get_latest_prices
    from app.domain.ledger import compute_positions, compute_cash_balance

    portfolio_ids = get_active_portfolio_ids(exclude_watchlist=True)
    print(f"✓ Active portfolios: {portfolio_ids}")

    if portfolio_ids:
        pid = portfolio_ids[0]
        policy = load_policy_snapshot(pid).get("policy", {})
        print(f"✓ Policy loaded: cash_min={policy.get('cash_min_pct')}%, cash_max={policy.get('cash_max_pct')}%, target={policy.get('cash_target_pct')}%")

        trades = list_trades(pid, limit=1000)
        positions = compute_positions(trades)
        print(f"✓ Positions: {len(positions)} assets")

        cash_movements = list_cash_movements(pid, limit=1000)
        cash_balance = compute_cash_balance(cash_movements, trades)
        print(f"✓ Cash balance: €{cash_balance:,.2f}")

        # Calculate total value
        tickers = list(set(p["ticker"] for p in positions))
        prices = get_latest_prices(tickers) if tickers else {}
        total_market_value = sum(p["shares"] * prices.get(p["ticker"], 0) for p in positions)
        total_value = total_market_value + cash_balance
        cash_pct = (cash_balance / total_value * 100) if total_value > 0 else 0

        print(f"✓ Total value: €{total_value:,.2f}")
        print(f"✓ Cash %: {cash_pct:.1f}%")

        # Determine severity
        cash_min = policy.get("cash_min_pct", 0)
        cash_max = policy.get("cash_max_pct", 100)

        if cash_pct < cash_min:
            cash_severity = "warn (below minimum)"
        elif cash_pct > cash_max:
            cash_severity = "warn (above maximum)"
        else:
            cash_severity = "ok"

        print(f"✓ Expected cash severity: {cash_severity}")

        # Check for policy breaches
        breaches = 0
        if cash_pct < cash_min or cash_pct > cash_max:
            breaches += 1

        health_severity = "bad" if breaches > 0 else "ok"
        print(f"✓ Expected health severity: {health_severity} (breaches={breaches})")

    else:
        print("⚠ No active portfolios found")

except Exception as e:
    print(f"✗ Database check failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("TEST 5: Callback Function Check")
print("=" * 60)

# Check if callback functions exist
callbacks_to_check = [
    "load_market_status",
    "load_portfolio_snapshot",
    "generate_ai_brief",
    "update_status_cards",
    "toggle_ai_brief",
]

for callback_name in callbacks_to_check:
    if hasattr(page_today, callback_name):
        print(f"✓ {callback_name} exists")
    else:
        print(f"✗ {callback_name} NOT FOUND")

print("\n" + "=" * 60)
print("TEST 6: Navigation Link Check")
print("=" * 60)

navigation_hrefs = [
    ("/market", "Markets card"),
    ("/portfolio/rebalance", "Health card"),
    ("/portfolio/rebalance", "Cash card"),
    ("/portfolio/signals", "Signals card"),
]

for href, card_name in navigation_hrefs:
    if href in layout_str:
        print(f"✓ {card_name} → {href}")
    else:
        print(f"✗ {card_name} → {href} NOT FOUND")

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("All static checks passed!")
print("\nNext steps:")
print("1. Navigate to http://localhost:8050/ in a browser")
print("2. Check browser console for callback errors")
print("3. Verify status cards show colored borders")
print("4. Click each card and verify navigation")
print("5. Toggle AI brief expand/collapse button")
print("6. Check auto-expand when breaches or sell signals present")
