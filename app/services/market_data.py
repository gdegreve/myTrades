"""Market data service with yfinance integration and caching.

Cache-first architecture:
1. Check SQLite cache for latest daily close prices
2. For stale or missing tickers, batch fetch from yfinance
3. Upsert fetched prices into cache transactionally
4. Return combined results

PRICE POLICY:
- Daily close only (interval='1d')
- Latest price = most recent available daily close
- No intraday, no live prices
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.prices_repo import get_latest_daily_closes, upsert_daily_closes

# Debug flag: set to True to print yfinance DataFrame structure diagnostics
DEBUG_YFINANCE = True


def get_latest_daily_closes_cached(
    tickers: list[str],
    max_age_minutes: int = 60,
    force_refresh: bool = False,
) -> tuple[dict[str, float], list[str]]:
    """Get latest daily close prices with cache-first strategy.

    Args:
        tickers: List of ticker symbols to fetch
        max_age_minutes: Maximum cache age in minutes (default 60)
        force_refresh: If True, bypass cache and force yfinance fetch

    Returns:
        Tuple of:
        - Dict mapping ticker -> close price (float)
        - List of tickers that failed to fetch (missing/error)

    Behavior:
        1. Query cache for all tickers
        2. Identify stale (fetched_at > max_age) or missing tickers
        3. Batch fetch missing/stale tickers from yfinance
        4. Upsert fresh prices into cache
        5. Return combined results

    Price Policy:
        - Uses yfinance.download with interval='1d', period='10d'
        - Takes most recent available daily close from returned data
        - Assumes prices are in EUR (no FX conversion yet)
    """
    if not tickers:
        return {}, []

    tickers_upper = [t.upper() for t in tickers]
    missing_tickers = []

    # Step 1: Check cache
    if force_refresh:
        cached_prices = {}
        to_fetch = tickers_upper
    else:
        cached_prices = get_latest_daily_closes(tickers_upper)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=max_age_minutes)

        # Separate fresh vs stale/missing
        fresh_prices = {}
        to_fetch = []

        for ticker in tickers_upper:
            if ticker in cached_prices:
                fetched_at_str = cached_prices[ticker]["fetched_at"]
                fetched_at = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))

                if fetched_at >= cutoff:
                    # Fresh cache hit
                    fresh_prices[ticker] = cached_prices[ticker]["close"]
                else:
                    # Stale, needs refresh
                    to_fetch.append(ticker)
            else:
                # Missing, needs fetch
                to_fetch.append(ticker)

        cached_prices = fresh_prices

    # Step 2: Batch fetch missing/stale tickers from yfinance
    if to_fetch:
        fetched_prices, fetch_errors = _fetch_yfinance_batch(to_fetch)

        # Step 3: Upsert fetched prices into cache
        if fetched_prices:
            bars_to_insert = [
                {
                    "symbol": ticker,
                    "date": data["date"],
                    "close": data["close"],
                    "currency": "EUR",  # Assume EUR for now
                    "provider": "yfinance",
                }
                for ticker, data in fetched_prices.items()
            ]
            try:
                upsert_daily_closes(bars_to_insert)
            except Exception as e:
                # Log error but don't fail the request
                print(f"Warning: Failed to cache prices: {e}")

        # Merge fetched prices with cached
        for ticker, data in fetched_prices.items():
            cached_prices[ticker] = data["close"]

        missing_tickers.extend(fetch_errors)

    return cached_prices, missing_tickers


def _fetch_yfinance_batch(tickers: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Batch fetch latest daily close prices from yfinance.

    Args:
        tickers: List of ticker symbols

    Returns:
        Tuple of:
        - Dict mapping ticker -> {"close": float, "date": str (YYYY-MM-DD)}
        - List of tickers that failed to fetch

    Implementation:
        - Uses yfinance.download() with group_by='ticker' for batch efficiency
        - Fetches 10 days of data to ensure recent close even on weekends/holidays
        - Takes most recent available date's close price
        - interval='1d', auto_adjust=False, progress=False for clean batch operation
        - Supports multiple yfinance DataFrame column layouts (MultiIndex variations)
    """
    try:
        import yfinance as yf
    except ImportError:
        # yfinance not installed - return all tickers as failed
        return {}, tickers

    if not tickers:
        return {}, []

    try:
        # Batch download: avoid per-ticker sequential calls
        data = yf.download(
            tickers=" ".join(tickers),
            interval="1d",
            period="10d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            #show_errors=False,
        )

        if DEBUG_YFINANCE:
            print(f"\n[DEBUG] yfinance batch fetch for {len(tickers)} ticker(s)")
            print(f"[DEBUG] DataFrame shape: {data.shape}")
            print(f"[DEBUG] DataFrame type: {type(data)}")
            if hasattr(data.columns, 'nlevels'):
                print(f"[DEBUG] Column levels: {data.columns.nlevels}")
            print(f"[DEBUG] Columns (first 10): {list(data.columns[:10])}")

        result = {}
        errors = []

        # Handle single ticker vs multiple tickers (different DataFrame structure)
        if len(tickers) == 1:
            ticker = tickers[0]
            close_series = None

            # Try multiple access patterns for single ticker
            if not data.empty:
                # Pattern 1: Flat columns with "Close"
                if "Close" in data.columns:
                    close_series = data["Close"].dropna()
                # Pattern 2: MultiIndex with (ticker, "Close")
                elif (ticker, "Close") in data.columns:
                    close_series = data[(ticker, "Close")].dropna()
                # Pattern 3: MultiIndex with ("Close", ticker)
                elif ("Close", ticker) in data.columns:
                    close_series = data[("Close", ticker)].dropna()
                # Pattern 4: Ticker as top-level column group
                elif ticker in data.columns:
                    try:
                        close_series = data[ticker]["Close"].dropna()
                    except (KeyError, TypeError):
                        pass

            if close_series is not None and not close_series.empty:
                latest_date = close_series.index[-1]
                latest_close = close_series.iloc[-1]
                result[ticker] = {
                    "close": float(latest_close),
                    "date": latest_date.strftime("%Y-%m-%d"),
                }
            else:
                errors.append(ticker)
        else:
            # Multiple tickers: data has multi-level columns
            # Try multiple access patterns for each ticker
            for ticker in tickers:
                close_series = None

                try:
                    # Pattern 1: MultiIndex (ticker, "Close")
                    if (ticker, "Close") in data.columns:
                        close_series = data[(ticker, "Close")].dropna()
                    # Pattern 2: MultiIndex ("Close", ticker)
                    elif ("Close", ticker) in data.columns:
                        close_series = data[("Close", ticker)].dropna()
                    # Pattern 3: Ticker as top-level column group
                    elif ticker in data.columns:
                        try:
                            close_series = data[ticker]["Close"].dropna()
                        except (KeyError, TypeError):
                            pass

                    if close_series is not None and not close_series.empty:
                        latest_date = close_series.index[-1]
                        latest_close = close_series.iloc[-1]
                        result[ticker] = {
                            "close": float(latest_close),
                            "date": latest_date.strftime("%Y-%m-%d"),
                        }
                    else:
                        errors.append(ticker)
                except Exception:
                    errors.append(ticker)

        if DEBUG_YFINANCE:
            print(f"[DEBUG] Successfully fetched: {list(result.keys())}")
            print(f"[DEBUG] Failed to fetch: {errors}\n")

        return result, errors

    except Exception as e:
        # Complete batch failure
        print(f"Error fetching yfinance data: {e}")
        return {}, tickers
