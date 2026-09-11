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
