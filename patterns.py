"""
patterns.py

Breakout pattern detection and technical indicators for daily_scan.py.

All functions take a pandas DataFrame with columns:
  Open, High, Low, Close, Volume  (index = DatetimeIndex, ascending)

Detection functions return a dict with:
  triggered: bool
  ... pattern-specific details (breakout_price, level, etc.)

Locked v1 patterns:
  - N-week high (N in {20, 55, 252})
  - Horizontal resistance break (tested cluster of swing highs)
  - Volatility contraction breakout (ATR compression then range expansion)

All patterns require volume >= 1.5x 20-day average on breakout day.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


VOLUME_MULTIPLE_THRESHOLD = 1.5


# ============================================================================
# Technical indicators
# ============================================================================

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def atr(prices: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder-smoothed)."""
    high = prices["High"]
    low = prices["Low"]
    prev_close = prices["Close"].shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def volume_multiple(prices: pd.DataFrame, lookback: int = 20) -> float | None:
    """Today's volume as a multiple of prior N-day average (excludes today)."""
    if len(prices) < lookback + 1:
        return None
    avg = prices["Volume"].iloc[-(lookback + 1):-1].mean()
    if avg <= 0:
        return None
    return float(prices["Volume"].iloc[-1] / avg)


def swing_low(prices: pd.DataFrame, lookback: int = 20) -> float | None:
    """Lowest low in the last N sessions (inclusive of today)."""
    if len(prices) < lookback:
        return None
    return float(prices["Low"].iloc[-lookback:].min())


def is_sma_rising(sma_series: pd.Series, lookback: int = 10) -> bool:
    """SMA now > SMA `lookback` sessions ago."""
    if len(sma_series.dropna()) < lookback + 1:
        return False
    return bool(sma_series.iloc[-1] > sma_series.iloc[-(lookback + 1)])


def high_52w_proximity(prices: pd.DataFrame) -> float | None:
    """Current close as a fraction of 52-week (252-session) high. 1.0 = at high."""
    if len(prices) < 20:
        return None
    lookback = min(252, len(prices))
    high_52w = float(prices["High"].iloc[-lookback:].max())
    if high_52w <= 0:
        return None
    return float(prices["Close"].iloc[-1] / high_52w)


def relative_strength_pct(stock: pd.DataFrame, index: pd.DataFrame, weeks: int) -> float | None:
    """Stock return minus index return over N weeks (5 trading days per week)."""
    sessions = weeks * 5
    if len(stock) < sessions + 1 or len(index) < sessions + 1:
        return None
    stock_ret = float(stock["Close"].iloc[-1] / stock["Close"].iloc[-(sessions + 1)] - 1)
    index_ret = float(index["Close"].iloc[-1] / index["Close"].iloc[-(sessions + 1)] - 1)
    return round((stock_ret - index_ret) * 100, 2)


def worst_recent_gap_down_pct(prices: pd.DataFrame, lookback: int = 20) -> float:
    """Worst overnight gap-down (as negative %) in the last N sessions.
    Returns 0.0 if none found. Gap = today's open vs prior close.
    """
    if len(prices) < lookback + 1:
        return 0.0
    recent = prices.iloc[-(lookback + 1):]
    prev_close = recent["Close"].shift(1)
    gap_pct = (recent["Open"] / prev_close - 1) * 100
    worst = float(gap_pct.min())
    return worst if worst < 0 else 0.0


# ============================================================================
# Momentum confluence indicators (RSI, ADX, Weekly MACD, 52W range position)
# ============================================================================

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Classic Wilder RSI."""
    delta = close.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def adx(prices: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder). Measures trend strength regardless
    of direction. ADX ≥ 20 = trending; < 20 = choppy / ranging."""
    high = prices["High"]
    low = prices["Low"]
    close = prices["Close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
    )

    atr_series = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    atr_safe = atr_series.replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_safe

    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def weekly_macd_histogram_positive(close: pd.Series) -> bool:
    """True if the latest weekly MACD(12,26,9) histogram is positive.
    Weekly MACD lagging-but-reliable confirmation of medium-term trend."""
    if len(close) < 150:  # need enough daily bars for 30+ weekly bars
        return False
    weekly = close.resample("W").last().dropna()
    if len(weekly) < 30:
        return False
    ema12 = weekly.ewm(span=12, adjust=False).mean()
    ema26 = weekly.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    last = histogram.iloc[-1]
    return bool(pd.notna(last) and float(last) > 0)


def range_52w_position(prices: pd.DataFrame) -> float | None:
    """Where current close sits in the 52-week range. 0 = at low, 1 = at high.
    Returns None if insufficient data."""
    if len(prices) < 252:
        return None
    window = prices.iloc[-252:]
    hi = float(window["High"].max())
    lo = float(window["Low"].min())
    cur = float(prices["Close"].iloc[-1])
    if hi <= lo:
        return None
    return (cur - lo) / (hi - lo)


def check_momentum_confluence(prices: pd.DataFrame) -> dict:
    """Four momentum/trend-quality checks. Returns per-check results plus total
    passed count. Caller decides minimum threshold (e.g., 3 of 4 required).

    Checks:
      - RSI(14) in 50-70 range (uptrending without being extended)
      - ADX(14) >= 20 (actually trending, not chopping)
      - Weekly MACD histogram positive (medium-term trend confirmed)
      - Price position in 52W range >= 60% (stock is in strength)
    """
    close = prices["Close"]
    rsi_val = float(rsi(close, 14).iloc[-1]) if len(close) >= 15 else None
    adx_val = float(adx(prices, 14).iloc[-1]) if len(prices) >= 28 else None
    weekly_macd_ok = weekly_macd_histogram_positive(close)
    range_pos = range_52w_position(prices)

    checks = {
        "rsi_50_70": rsi_val is not None and 50 <= rsi_val <= 70,
        "adx_20_plus": adx_val is not None and adx_val >= 20,
        "weekly_macd_positive": weekly_macd_ok,
        "range_pos_60_plus": range_pos is not None and range_pos >= 0.60,
    }
    passed = sum(checks.values())
    return {
        "checks": checks,
        "passed": passed,
        "total": 4,
        "rsi": round(rsi_val, 1) if rsi_val is not None and not pd.isna(rsi_val) else None,
        "adx": round(adx_val, 1) if adx_val is not None and not pd.isna(adx_val) else None,
        "range_pos_pct": round(range_pos * 100, 1) if range_pos is not None else None,
    }


# ============================================================================
# Momentum indicators (for the confluence filter)
# ============================================================================

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder-smoothed Relative Strength Index."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs_val = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs_val))


def adx(prices: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder). High ADX = strong trend; low = chop."""
    high = prices["High"]
    low = prices["Low"]
    close = prices["Close"]

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_val = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move.clip(lower=0)

    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_val
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_val

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD line, signal line, histogram. Returns tuple of three Series."""
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def range_position_52w(prices: pd.DataFrame) -> float | None:
    """Current close as fraction of 52-week range (0 = at low, 1 = at high)."""
    if len(prices) < 60:
        return None
    lookback = min(252, len(prices))
    hi = float(prices["High"].iloc[-lookback:].max())
    lo = float(prices["Low"].iloc[-lookback:].min())
    if hi <= lo:
        return None
    close_now = float(prices["Close"].iloc[-1])
    return (close_now - lo) / (hi - lo)


# ============================================================================
# Days-in-consolidation heuristic
# ============================================================================

def days_since_prior_high(prices: pd.DataFrame, lookback: int = 200) -> int:
    """Number of sessions since the last time price closed at a fresh 60-day high.

    Longer values mean a longer consolidation/base preceded today's move.
    Capped at `lookback`.
    """
    if len(prices) < 60:
        return 0
    window = prices.iloc[-lookback:] if len(prices) > lookback else prices
    closes = window["Close"].values
    days_since = 0
    for i in range(len(closes) - 2, -1, -1):
        window_start = max(0, i - 60)
        prior_high = closes[window_start:i].max() if i > window_start else 0
        if closes[i] > prior_high:
            break
        days_since += 1
    return days_since


# ============================================================================
# Breakout patterns
# ============================================================================

def detect_n_week_high(prices: pd.DataFrame, n_sessions: int) -> dict:
    """Today's close > max(High) over prior N sessions (exclusive of today)."""
    result = {"triggered": False, "n_sessions": n_sessions}
    if len(prices) < n_sessions + 1:
        return result
    prior_high = float(prices["High"].iloc[-(n_sessions + 1):-1].max())
    today_close = float(prices["Close"].iloc[-1])
    if today_close > prior_high:
        vol_mult = volume_multiple(prices)
        if vol_mult is not None and vol_mult >= VOLUME_MULTIPLE_THRESHOLD:
            result.update({
                "triggered": True,
                "breakout_level": round(prior_high, 2),
                "close": round(today_close, 2),
                "volume_multiple": round(vol_mult, 2),
            })
    return result


def detect_horizontal_resistance_break(prices: pd.DataFrame, lookback: int = 60) -> dict:
    """Break above a tested horizontal resistance cluster.

    Logic:
      1. Take highs over the last `lookback` sessions (excluding last 5, to
         avoid the current momentum leg biasing the resistance level).
      2. Take the 95th-percentile high as the resistance level.
      3. Count "touches": sessions with high within 1.5% of that level.
      4. Trigger if today's close > level AND touches >= 2 AND vol >= 1.5x avg.
    """
    result = {"triggered": False}
    if len(prices) < lookback + 5:
        return result

    window = prices["High"].iloc[-(lookback + 5):-5]
    if window.empty:
        return result

    resistance = float(np.percentile(window, 95))
    touches = int((window >= resistance * 0.985).sum())
    today_close = float(prices["Close"].iloc[-1])

    if today_close > resistance and touches >= 2:
        vol_mult = volume_multiple(prices)
        if vol_mult is not None and vol_mult >= VOLUME_MULTIPLE_THRESHOLD:
            result.update({
                "triggered": True,
                "resistance_level": round(resistance, 2),
                "touches": touches,
                "close": round(today_close, 2),
                "volume_multiple": round(vol_mult, 2),
            })
    return result


def detect_volatility_contraction_break(prices: pd.DataFrame) -> dict:
    """Break above recent range after ATR compression.

    Logic:
      1. ATR(14) has contracted: ATR_now < 0.8 * ATR_20-ago.
      2. Today's close > max close of prior 20 sessions.
      3. Volume confirmed.
    """
    result = {"triggered": False}
    if len(prices) < 35:
        return result

    atr_series = atr(prices, 14)
    if atr_series.isna().iloc[-1] or atr_series.isna().iloc[-21]:
        return result

    atr_now = float(atr_series.iloc[-1])
    atr_20_ago = float(atr_series.iloc[-21])
    if atr_20_ago <= 0:
        return result
    contraction_ratio = atr_now / atr_20_ago

    range_high = float(prices["Close"].iloc[-21:-1].max())
    today_close = float(prices["Close"].iloc[-1])

    if contraction_ratio < 0.8 and today_close > range_high:
        vol_mult = volume_multiple(prices)
        if vol_mult is not None and vol_mult >= VOLUME_MULTIPLE_THRESHOLD:
            result.update({
                "triggered": True,
                "range_high": round(range_high, 2),
                "contraction_ratio": round(contraction_ratio, 3),
                "close": round(today_close, 2),
                "volume_multiple": round(vol_mult, 2),
            })
    return result


# ============================================================================
# Aggregated pattern scan for one stock
# ============================================================================

def scan_all_patterns(prices: pd.DataFrame) -> dict:
    """Run all v1 patterns. Returns dict keyed by pattern name.

    Always returns the four pattern results; each has a 'triggered' bool.
    """
    return {
        "n_week_20": detect_n_week_high(prices, 20),
        "n_week_55": detect_n_week_high(prices, 55),
        "n_week_252": detect_n_week_high(prices, 252),
        "horizontal_resistance": detect_horizontal_resistance_break(prices),
        "volatility_contraction": detect_volatility_contraction_break(prices),
    }


def any_triggered(patterns: dict) -> bool:
    return any(p.get("triggered") for p in patterns.values())


def pattern_labels(patterns: dict) -> list[str]:
    """Compact human-readable labels for triggered patterns."""
    labels = []
    if patterns["n_week_252"]["triggered"]: labels.append("52W High")
    elif patterns["n_week_55"]["triggered"]: labels.append("55D High")
    elif patterns["n_week_20"]["triggered"]: labels.append("20D High")
    if patterns["horizontal_resistance"]["triggered"]: labels.append("Resistance Break")
    if patterns["volatility_contraction"]["triggered"]: labels.append("VCP Break")
    return labels
