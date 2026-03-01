#!/usr/bin/env python3
"""Backfill price_currency and fx_rate for existing transactions.

Run once after deploying currency conversion changes.
This script ensures all existing transactions have proper currency metadata.

Usage:
    python scripts/migrate_currency_data.py [--dry-run]

Options:
    --dry-run    Show what would be changed without making changes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db.connection import get_connection
from app.services.fx_service import get_ticker_currency, get_fx_rate


def migrate_transactions(dry_run: bool = False) -> None:
    """Backfill currency data for existing transactions.

    Strategy:
        1. Find all transactions missing price_currency or fx_rate
        2. For each:
           - Detect actual ticker currency via yfinance
           - If currency is EUR: set fx_rate=1.0, price_currency='EUR'
           - If non-EUR and price_eur exists: back-calculate fx_rate from price/price_eur
           - If non-EUR and price_eur missing: fetch historical FX rate and convert

    Args:
        dry_run: If True, show changes without committing
    """
    with get_connection() as conn:
        # Find transactions needing migration
        rows = conn.execute(
            """
            SELECT id, ticker, price, price_eur, transaction_date, price_currency, fx_rate
            FROM transactions
            WHERE price_currency IS NULL OR price_currency = '' OR fx_rate IS NULL OR fx_rate = 0
            ORDER BY transaction_date ASC, id ASC
            """
        ).fetchall()

        if not rows:
            print("✅ No transactions need migration. All currency data is complete.")
            return

        print(f"Found {len(rows)} transactions needing currency migration")
        print()

        updates = []
        errors = []

        for row in rows:
            tid = row["id"]
            ticker = row["ticker"]
            price = row["price"]
            price_eur = row["price_eur"]
            date = row["transaction_date"]
            existing_currency = row["price_currency"]
            existing_fx_rate = row["fx_rate"]

            # Detect actual currency
            try:
                currency = get_ticker_currency(ticker)
            except Exception as e:
                errors.append(f"  ❌ ID {tid} ({ticker}): Failed to detect currency: {e}")
                currency = "USD"  # Fallback

            if currency == "EUR":
                # EUR ticker: simple case
                updates.append({
                    "id": tid,
                    "ticker": ticker,
                    "price_currency": "EUR",
                    "price": price or price_eur or 0.0,
                    "price_eur": price_eur or price or 0.0,
                    "fx_rate": 1.0,
                })
                print(f"  ✓ ID {tid} ({ticker}): EUR ticker, fx_rate=1.0")

            else:
                # Non-EUR ticker: need FX conversion
                if price and price_eur and price_eur > 0:
                    # Back-calculate FX rate from existing data
                    # price_eur = price / fx_rate → fx_rate = price / price_eur
                    calculated_fx_rate = price / price_eur
                    updates.append({
                        "id": tid,
                        "ticker": ticker,
                        "price_currency": currency,
                        "price": price,
                        "price_eur": price_eur,
                        "fx_rate": calculated_fx_rate,
                    })
                    print(f"  ✓ ID {tid} ({ticker}): Back-calculated fx_rate={calculated_fx_rate:.4f} from existing data")

                elif price and price > 0:
                    # Fetch historical FX rate and calculate price_eur
                    try:
                        fx_rate = get_fx_rate("EUR", currency, date, fetch_if_missing=True)
                        if fx_rate is None or fx_rate == 0:
                            # Fallback to latest rate
                            fx_rate = get_fx_rate("EUR", currency, None, fetch_if_missing=True)
                            if fx_rate is None or fx_rate == 0:
                                fx_rate = 1.0  # Ultimate fallback
                                errors.append(f"  ⚠️  ID {tid} ({ticker}): FX rate unavailable, using fallback 1.0")

                        calculated_price_eur = price / fx_rate

                        updates.append({
                            "id": tid,
                            "ticker": ticker,
                            "price_currency": currency,
                            "price": price,
                            "price_eur": calculated_price_eur,
                            "fx_rate": fx_rate,
                        })
                        print(f"  ✓ ID {tid} ({ticker}): Fetched fx_rate={fx_rate:.4f}, calculated price_eur={calculated_price_eur:.2f}")

                    except Exception as e:
                        errors.append(f"  ❌ ID {tid} ({ticker}): FX conversion failed: {e}")
                        # Use fallback
                        updates.append({
                            "id": tid,
                            "ticker": ticker,
                            "price_currency": currency,
                            "price": price,
                            "price_eur": price or 0.0,
                            "fx_rate": 1.0,
                        })

                else:
                    # No valid price data
                    errors.append(f"  ⚠️  ID {tid} ({ticker}): No valid price data, using defaults")
                    updates.append({
                        "id": tid,
                        "ticker": ticker,
                        "price_currency": currency,
                        "price": 0.0,
                        "price_eur": 0.0,
                        "fx_rate": 1.0,
                    })

        print()
        print("=" * 80)
        print(f"Migration Summary: {len(updates)} transactions to update")
        print("=" * 80)

        if errors:
            print()
            print("Warnings/Errors:")
            for error in errors:
                print(error)
            print()

        if dry_run:
            print()
            print("🔍 DRY RUN MODE - No changes committed")
            print("   Remove --dry-run flag to apply changes")
            return

        # Apply updates
        print()
        print("Applying updates...")
        for update in updates:
            conn.execute(
                """
                UPDATE transactions
                SET price_currency = ?,
                    price = ?,
                    price_eur = ?,
                    fx_rate = ?
                WHERE id = ?
                """,
                (
                    update["price_currency"],
                    update["price"],
                    update["price_eur"],
                    update["fx_rate"],
                    update["id"],
                ),
            )

        conn.commit()
        print(f"✅ Successfully migrated {len(updates)} transactions")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill currency data for existing transactions"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without committing",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("Multi-Currency Migration Script")
    print("=" * 80)
    print()

    try:
        migrate_transactions(dry_run=args.dry_run)
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
