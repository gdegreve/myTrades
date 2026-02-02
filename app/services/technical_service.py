"""Technical analysis service with yfinance integration and caching.

Provides OHLCV data fetching, technical indicators computation, and signal analysis.
"""

from __future__ import annotations

import time
from datetime import datetime

import pandas as pd

# LRU + TTL cache for OHLCV data
_ohlcv_cache = {}  # {(ticker, period, interval): (df, timestamp)}
_cache_order = []  # LRU tracking
MAX_CACHE_SIZE = 50
CACHE_TTL = 15 * 60  # 15 minutes


def get_ohlcv_data(ticker: str, period: str) -> tuple[pd.DataFrame | None, str]:
    """Fetch OHLCV data with caching.

    Args:
        ticker: Stock ticker symbol
        period: Time period (e.g., "1y", "6mo", "3mo")

    Returns:
        Tuple of (DataFrame with OHLCV + indicators, error_message)
        Returns (None, error) on failure
    """
    cache_key = (ticker, period, "1d")
    now = time.time()

    # Check cache
    if cache_key in _ohlcv_cache:
        cached_df, cached_time = _ohlcv_cache[cache_key]
        if now - cached_time < CACHE_TTL:
            # Cache hit
            _cache_order.remove(cache_key)
            _cache_order.append(cache_key)
            return cached_df.copy(), ""

    # Cache miss - fetch from yfinance
    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance library not available"

    try:
        df = yf.download(ticker, period=period, interval="1d", progress=False)

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        if df.empty:
            return None, f"No data available for {ticker}"

        # Cap to last 800 bars
        if len(df) > 800:
            df = df.iloc[-800:]

        # Compute indicators
        df = compute_indicators(df)

        # Cache result
        if len(_ohlcv_cache) >= MAX_CACHE_SIZE:
            oldest_key = _cache_order.pop(0)
            del _ohlcv_cache[oldest_key]

        _ohlcv_cache[cache_key] = (df.copy(), now)
        _cache_order.append(cache_key)

        return df, ""

    except Exception as e:
        return None, f"Error fetching data for {ticker}: {str(e)}"


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical indicators on OHLCV DataFrame.

    Args:
        df: DataFrame with OHLC columns (from yfinance)

    Returns:
        DataFrame with added indicator columns
    """
    # Flatten MultiIndex columns if present and make a copy
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.copy()

    # Try pandas_ta first, fallback to manual calculations
    try:
        import pandas_ta as ta

        df.ta.sma(length=20, append=True, col_names=("SMA_20",))
        df.ta.sma(length=50, append=True, col_names=("SMA_50",))
        df.ta.sma(length=200, append=True, col_names=("SMA_200",))
        df.ta.ema(length=20, append=True, col_names=("EMA_20",))
        df.ta.ema(length=50, append=True, col_names=("EMA_50",))
        df.ta.bbands(length=20, std=2, append=True)
        df.ta.rsi(length=14, append=True, col_names=("RSI",))
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        df.ta.adx(length=14, append=True)
        df.ta.atr(length=14, append=True, col_names=("ATR",))

        # Extract ADX column if it was appended
        adx_cols = [c for c in df.columns if str(c).upper().startswith("ADX_")]
        if adx_cols:
            df["ADX"] = df[adx_cols[0]]

        # Rename pandas_ta columns to our standard names
        if "BBL_20_2.0" in df.columns:
            df.rename(
                columns={
                    "BBL_20_2.0": "BB_Lower",
                    "BBM_20_2.0": "BB_Middle",
                    "BBU_20_2.0": "BB_Upper",
                    "MACD_12_26_9": "MACD",
                    "MACDs_12_26_9": "MACD_Signal",
                    "MACDh_12_26_9": "MACD_Hist",
                },
                inplace=True,
            )

    except ImportError:
        # Manual calculations fallback
        df["SMA_20"] = df["Close"].rolling(20).mean()
        df["SMA_50"] = df["Close"].rolling(50).mean()
        df["SMA_200"] = df["Close"].rolling(200).mean()
        df["EMA_20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA_50"] = df["Close"].ewm(span=50, adjust=False).mean()

        # Bollinger Bands
        bb_middle = df["Close"].rolling(20).mean()
        bb_std = df["Close"].rolling(20).std()
        df["BB_Lower"] = bb_middle - 2 * bb_std
        df["BB_Middle"] = bb_middle
        df["BB_Upper"] = bb_middle + 2 * bb_std

        # RSI
        delta = df["Close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df["RSI"] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = ema12 - ema26
        df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

        # ATR
        high_low = df["High"] - df["Low"]
        high_close = abs(df["High"] - df["Close"].shift())
        low_close = abs(df["Low"] - df["Close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()

        # ADX (simplified version)
        plus_dm = df["High"].diff()
        minus_dm = -df["Low"].diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        atr = df["ATR"]
        plus_di = 100 * (plus_dm.rolling(14).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(14).mean() / atr)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df["ADX"] = dx.rolling(14).mean()

    # ATR%
    df["ATR_Pct"] = (df["ATR"] / df["Close"]) * 100

    # Daily change %
    df["Daily_Change"] = df["Close"].pct_change() * 100

    return df


def analyze_technical_signal(df: pd.DataFrame) -> dict:
    """Analyze technical signal from OHLCV + indicators.

    Args:
        df: DataFrame with OHLCV and computed indicators

    Returns:
        Dict with signal analysis results
    """
    if df.empty:
        return {
            "signal_type": "UNKNOWN",
            "signal_name": "No Data",
            "setup_quality_score": 0,
            "trend_direction": "Unknown",
            "rsi": 0,
            "adx": 0,
            "atr_pct": 0,
            "volatility_level": "Unknown",
            "momentum": "Unknown",
            "reasons": [],
        }

    latest = df.iloc[-1]
    score = 50  # Base score

    reasons = []

    # Extract values (handle NaN)
    ema20 = latest.get("EMA_20", 0) or 0
    ema50 = latest.get("EMA_50", 0) or 0
    rsi = latest.get("RSI", 50) or 50
    adx = latest.get("ADX", 0) or 0
    atr_pct = latest.get("ATR_Pct", 0) or 0
    macd = latest.get("MACD", 0) or 0
    macd_signal = latest.get("MACD_Signal", 0) or 0
    bb_upper = latest.get("BB_Upper", 0) or 0
    bb_lower = latest.get("BB_Lower", 0) or 0
    close = latest.get("Close", 0) or 0
    daily_change = latest.get("Daily_Change", 0) or 0

    # Trend: EMA20 vs EMA50
    if ema20 > ema50:
        score += 10
        trend_direction = "Bullish"
        reasons.append("Bullish trend (EMA20 > EMA50)")
    elif ema20 < ema50:
        score -= 10
        trend_direction = "Bearish"
        reasons.append("Bearish trend (EMA20 < EMA50)")
    else:
        trend_direction = "Neutral"
        reasons.append("Neutral trend")

    # RSI
    if rsi > 70:
        score -= 15
        reasons.append(f"Overbought (RSI {rsi:.1f})")
    elif rsi < 30:
        score -= 10
        reasons.append(f"Oversold (RSI {rsi:.1f})")
    elif 40 <= rsi <= 60:
        score += 10
        reasons.append(f"Balanced RSI ({rsi:.1f})")
    else:
        reasons.append(f"RSI {rsi:.1f}")

    # ADX
    if adx > 25:
        score += 15
        reasons.append(f"Strong trend strength (ADX {adx:.1f})")
    elif adx > 20:
        score += 5
        reasons.append(f"Moderate trend strength (ADX {adx:.1f})")
    else:
        score -= 10
        reasons.append(f"Weak trend (ADX {adx:.1f})")

    # Bollinger position
    if close > bb_upper:
        score -= 10
        reasons.append("Price above upper Bollinger Band")
    elif close < bb_lower:
        score -= 5
        reasons.append("Price below lower Bollinger Band")

    # MACD
    if macd > macd_signal:
        score += 10
        reasons.append("Bullish MACD cross")
    else:
        score -= 10
        reasons.append("Bearish MACD cross")

    # Clamp score 0-100
    score = max(0, min(100, score))

    # Signal type
    if score >= 70:
        signal_type = "GO"
    elif score <= 40:
        signal_type = "STOP"
    else:
        signal_type = "CAUTION"

    # Signal name (based on trend + ADX + RSI)
    if trend_direction == "Bullish" and adx > 25 and 40 <= rsi <= 70:
        signal_name = "Strong Bullish Setup"
    elif trend_direction == "Bullish" and adx > 20:
        signal_name = "Bullish Momentum"
    elif trend_direction == "Bearish" and adx > 25:
        signal_name = "Strong Bearish Setup"
    elif trend_direction == "Bearish":
        signal_name = "Bearish Momentum"
    elif rsi > 70:
        signal_name = "Overbought Warning"
    elif rsi < 30:
        signal_name = "Oversold Opportunity"
    else:
        signal_name = "Neutral / Consolidation"

    # Momentum
    if daily_change > 2:
        momentum = "Strong Up"
    elif daily_change > 1:
        momentum = "Up"
    elif daily_change > 0:
        momentum = "Slight Up"
    elif daily_change > -1:
        momentum = "Slight Down"
    elif daily_change > -2:
        momentum = "Down"
    else:
        momentum = "Strong Down"

    # Volatility
    if atr_pct < 2:
        volatility_level = "Low"
    elif atr_pct < 4:
        volatility_level = "Medium"
    else:
        volatility_level = "High"

    return {
        "signal_type": signal_type,
        "signal_name": signal_name,
        "setup_quality_score": score,
        "trend_direction": trend_direction,
        "rsi": rsi,
        "adx": adx,
        "atr_pct": atr_pct,
        "volatility_level": volatility_level,
        "momentum": momentum,
        "reasons": reasons,
    }
