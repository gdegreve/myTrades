"""FX (Foreign Exchange) service for multi-currency portfolio support.

Provides:
1. Currency detection: Identify ticker's native currency from yfinance
2. FX rate fetching: Get exchange rates from yfinance (EURUSD=X format)
3. EUR conversion: Convert any currency amount to EUR with caching

All FX rates are stored in database for historical consistency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, date as dt_date
from typing import Any

from app.db.fx_rates_repo import get_latest_fx_rate, get_fx_rate_on_date, upsert_fx_rates

# In-memory cache for ticker currency (TTL: 1 hour)
# Structure: {ticker: (currency, timestamp)}
_TICKER_CURRENCY_CACHE: dict[str, tuple[str, datetime]] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def get_ticker_currency(ticker: str) -> str:
    """Detect native currency for a given ticker symbol.

    Args:
        ticker: Ticker symbol (e.g., "AAPL", "SAP.DE", "HSBA.L")

    Returns:
        3-letter currency code (e.g., "USD", "EUR", "GBP")
        Defaults to "USD" on error or if unavailable.

    Implementation:
        Uses yfinance Ticker.info["currency"] to detect currency.
        Results are cached in memory (1-hour TTL) to avoid repeated API calls.

    Examples:
        get_ticker_currency("AAPL") → "USD"
        get_ticker_currency("SAP.DE") → "EUR"
        get_ticker_currency("HSBA.L") → "GBP"
    """
    if not ticker:
        return "USD"

    ticker_upper = ticker.upper()

    # Check in-memory cache
    now = datetime.now()
    if ticker_upper in _TICKER_CURRENCY_CACHE:
        cached_currency, cached_time = _TICKER_CURRENCY_CACHE[ticker_upper]
        if (now - cached_time).total_seconds() < _CACHE_TTL_SECONDS:
            return cached_currency

    # Fetch from yfinance
    try:
        import yfinance as yf
        ticker_obj = yf.Ticker(ticker_upper)
        info = ticker_obj.info
        currency = info.get("currency", "USD")

        # Validate currency code (should be 3 uppercase letters)
        if isinstance(currency, str) and len(currency) == 3:
            currency = currency.upper()
        else:
            currency = "USD"

        # Cache result
        _TICKER_CURRENCY_CACHE[ticker_upper] = (currency, now)
        return currency

    except Exception as e:
        print(f"Warning: Failed to detect currency for {ticker_upper}: {e}")
        # Cache failure as USD to avoid repeated API calls
        _TICKER_CURRENCY_CACHE[ticker_upper] = ("USD", now)
        return "USD"


def fetch_fx_rates_batch(
    currency_pairs: list[tuple[str, str]],
    date: str | None = None,
) -> dict[tuple[str, str], float]:
    """Fetch FX rates for multiple currency pairs from yfinance.

    Args:
        currency_pairs: List of (base, quote) tuples, e.g., [("EUR", "USD"), ("EUR", "GBP")]
        date: Optional ISO date (YYYY-MM-DD). If None, fetch latest rates.

    Returns:
        Dict mapping (base, quote) → rate
        Example: {("EUR", "USD"): 1.08, ("EUR", "GBP"): 0.86}
        Missing pairs are excluded from result.

    Implementation:
        Uses yfinance ticker format: "EURUSD=X" for EUR/USD
        Auto-caches results in database via fx_rates_repo

    Note:
        yfinance uses format: BASEQUOTE=X (e.g., EURUSD=X, EURGBP=X)
        Rate is always quote per base: EURUSD=X rate 1.08 means 1 EUR = 1.08 USD
    """
    if not currency_pairs:
        return {}

    try:
        import yfinance as yf
    except ImportError:
        print("Warning: yfinance not installed, cannot fetch FX rates")
        return {}

    result = {}
    rates_to_cache = []

    for base, quote in currency_pairs:
        base_upper = base.upper()
        quote_upper = quote.upper()

        # Special case: same currency
        if base_upper == quote_upper:
            result[(base_upper, quote_upper)] = 1.0
            continue

        # Build yfinance ticker format: BASEQUOTE=X
        fx_ticker = f"{base_upper}{quote_upper}=X"

        try:
            if date:
                # Fetch historical rate for specific date
                # yfinance needs a date range, so fetch ±2 days around target
                target_date = datetime.fromisoformat(date).date()
                start_date = target_date - timedelta(days=2)
                end_date = target_date + timedelta(days=2)

                data = yf.download(
                    fx_ticker,
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    progress=False,
                )

                if not data.empty and "Close" in data.columns:
                    # Find closest date to target
                    data = data.dropna(subset=["Close"])
                    if not data.empty:
                        closest_idx = (data.index.date - target_date).abs().argmin()
                        rate = float(data["Close"].iloc[closest_idx])
                        rate_date = data.index[closest_idx].strftime("%Y-%m-%d")

                        result[(base_upper, quote_upper)] = rate
                        rates_to_cache.append({
                            "base_currency": base_upper,
                            "quote_currency": quote_upper,
                            "rate": rate,
                            "date": rate_date,
                        })
            else:
                # Fetch latest rate (last 5 days to ensure data)
                data = yf.download(fx_ticker, period="5d", progress=False)

                if not data.empty and "Close" in data.columns:
                    close_series = data["Close"].dropna()
                    if not close_series.empty:
                        rate = float(close_series.iloc[-1])
                        rate_date = close_series.index[-1].strftime("%Y-%m-%d")

                        result[(base_upper, quote_upper)] = rate
                        rates_to_cache.append({
                            "base_currency": base_upper,
                            "quote_currency": quote_upper,
                            "rate": rate,
                            "date": rate_date,
                        })

        except Exception as e:
            print(f"Warning: Failed to fetch FX rate for {fx_ticker}: {e}")
            continue

    # Cache fetched rates in database
    if rates_to_cache:
        try:
            upsert_fx_rates(rates_to_cache)
        except Exception as e:
            print(f"Warning: Failed to cache FX rates: {e}")

    return result


def get_fx_rate(
    base: str,
    quote: str,
    date: str | None = None,
    fetch_if_missing: bool = True,
) -> float | None:
    """Get FX rate for currency pair, with optional date and auto-fetch.

    Args:
        base: Base currency (e.g., "EUR")
        quote: Quote currency (e.g., "USD")
        date: Optional ISO date (YYYY-MM-DD). If None, use latest.
        fetch_if_missing: If True and rate not in DB, fetch from yfinance.

    Returns:
        Exchange rate (float) or None if unavailable.
        Example: get_fx_rate("EUR", "USD") → 1.08 means 1 EUR = 1.08 USD

    Behavior:
        1. Check database cache
        2. If missing and fetch_if_missing=True, fetch from yfinance
        3. Return rate or None

    Special cases:
        - Same currency (EUR→EUR): returns 1.0
        - Inverse pair (USD→EUR but only EUR→USD in DB): returns 1/rate
    """
    base_upper = base.upper()
    quote_upper = quote.upper()

    # Special case: same currency
    if base_upper == quote_upper:
        return 1.0

    # Try database first
    if date:
        rate = get_fx_rate_on_date(base_upper, quote_upper, date)
    else:
        rate = get_latest_fx_rate(base_upper, quote_upper)

    if rate is not None:
        return rate

    # Try inverse pair (USD→EUR becomes 1 / EUR→USD)
    if date:
        inverse_rate = get_fx_rate_on_date(quote_upper, base_upper, date)
    else:
        inverse_rate = get_latest_fx_rate(quote_upper, base_upper)

    if inverse_rate is not None and inverse_rate != 0:
        return 1.0 / inverse_rate

    # Fetch from yfinance if missing
    if fetch_if_missing:
        fetched = fetch_fx_rates_batch([(base_upper, quote_upper)], date)
        return fetched.get((base_upper, quote_upper))

    return None


def convert_to_eur(
    amount: float,
    currency: str,
    date: str | None = None,
) -> tuple[float, float]:
    """Convert amount from native currency to EUR.

    Args:
        amount: Amount in native currency
        currency: Native currency code (e.g., "USD", "GBP")
        date: Optional ISO date for historical conversion. If None, use latest rate.

    Returns:
        Tuple of (converted_amount_eur, fx_rate_used)
        Example: convert_to_eur(100, "USD") → (92.59, 0.9259)

    Behavior:
        - If currency is "EUR", returns (amount, 1.0)
        - Otherwise, fetches FX rate and converts
        - If FX rate unavailable, returns (amount, 1.0) and logs warning

    FX Rate Logic:
        We need quote-per-base, so EUR is the base.
        For USD→EUR: get rate for EUR/USD (e.g., 1.08), then amount_eur = amount_usd / rate
        This gives us: amount_usd / (usd_per_eur) = amount_eur
    """
    if not currency:
        return amount, 1.0

    currency_upper = currency.upper()

    # Special case: already EUR
    if currency_upper == "EUR":
        return amount, 1.0

    # Get FX rate: EUR/CURRENCY (e.g., EUR/USD)
    # This means "how many CURRENCY units per 1 EUR"
    fx_rate = get_fx_rate("EUR", currency_upper, date, fetch_if_missing=True)

    if fx_rate is None or fx_rate == 0:
        print(f"Warning: FX rate for EUR/{currency_upper} unavailable on {date or 'latest'}. Using fallback 1.0")
        return amount, 1.0

    # Convert: amount_eur = amount_currency / (currency_per_eur)
    # Example: 100 USD / 1.08 (USD/EUR) = 92.59 EUR
    amount_eur = amount / fx_rate

    return amount_eur, fx_rate


def prefetch_fx_rates_for_tickers(tickers: list[str], date: str | None = None) -> None:
    """Prefetch and cache FX rates for multiple tickers (optimization).

    Args:
        tickers: List of ticker symbols
        date: Optional date for historical rates

    Behavior:
        Detects currency for each ticker, then batch-fetches FX rates to EUR.
        Useful for warming cache before portfolio calculations.
    """
    if not tickers:
        return

    # Detect currencies for all tickers
    currency_set = set()
    for ticker in tickers:
        currency = get_ticker_currency(ticker)
        if currency != "EUR":
            currency_set.add(currency)

    if not currency_set:
        return  # All tickers are EUR

    # Build currency pairs (EUR as base)
    pairs = [("EUR", curr) for curr in currency_set]

    # Batch fetch FX rates
    try:
        fetch_fx_rates_batch(pairs, date)
    except Exception as e:
        print(f"Warning: Failed to prefetch FX rates: {e}")
