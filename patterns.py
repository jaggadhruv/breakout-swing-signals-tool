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


def supertrend_state(
    prices: pd.DataFrame, atr_period: int = 10, multiplier: float = 2.5
) -> dict | None:
    """Compute Supertrend state matching TradingView free tier (ATR 10, mult 2.5).

    Returns {
      direction: +1 (long) or -1 (short)
      level: current trailing stop value (= Supertrend line)
      days_since_flip: bars since last direction change (0 = flipped today)
      stop_distance_pct: how far current close sits above the stop, as %
    }
    Or None if insufficient data.
    """
    if len(prices) < atr_period + 20:
        return None

    high = prices["High"]
    low = prices["Low"]
    close = prices["Close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_series = tr.ewm(alpha=1 / atr_period, adjust=False, min_periods=atr_period).mean()

    hl2 = (high + low) / 2
    basic_upper = hl2 + multiplier * atr_series
    basic_lower = hl2 - multiplier * atr_series

    n = len(prices)
    final_upper = basic_upper.to_numpy().copy()
    final_lower = basic_lower.to_numpy().copy()
    supertrend = np.empty(n)
    direction = np.empty(n, dtype=int)

    # Iteratively compute final bands and direction state
    for i in range(n):
        if i == 0 or np.isnan(final_upper[i]) or np.isnan(final_lower[i]):
            supertrend[i] = final_upper[i] if not np.isnan(final_upper[i]) else np.nan
            direction[i] = -1
            continue

        # Carry final upper band forward unless invalidated
        if basic_upper.iloc[i] >= final_upper[i - 1] and close.iloc[i - 1] <= final_upper[i - 1]:
            final_upper[i] = final_upper[i - 1]
        # (otherwise use basic_upper as-is, already assigned)

        # Carry final lower band forward unless invalidated
        if basic_lower.iloc[i] <= final_lower[i - 1] and close.iloc[i - 1] >= final_lower[i - 1]:
            final_lower[i] = final_lower[i - 1]

        prev_st = supertrend[i - 1]
        prev_dir = direction[i - 1]

        # State transition (TradingView-standard)
        if prev_dir == -1:
            # Previously short — flip to long if close breaks above upper
            if close.iloc[i] > final_upper[i]:
                supertrend[i] = final_lower[i]
                direction[i] = 1
            else:
                supertrend[i] = final_upper[i]
                direction[i] = -1
        else:
            # Previously long — flip to short if close breaks below lower
            if close.iloc[i] < final_lower[i]:
                supertrend[i] = final_upper[i]
                direction[i] = -1
            else:
                supertrend[i] = final_lower[i]
                direction[i] = 1

    # Count bars since last direction change
    current_dir = int(direction[-1])
    days_since_flip = 0
    for i in range(n - 2, -1, -1):
        if direction[i] != current_dir:
            break
        days_since_flip += 1

    current_close = float(close.iloc[-1])
    current_level = float(supertrend[-1])
    if np.isnan(current_level):
        return None

    # Distance from stop as positive % when long, negative when short
    if current_dir == 1:
        stop_distance_pct = (current_close - current_level) / current_level * 100
    else:
        stop_distance_pct = (current_close - current_level) / current_level * 100  # will be negative

    return {
        "direction": current_dir,
        "level": round(current_level, 2),
        "days_since_flip": int(days_since_flip),
        "stop_distance_pct": round(float(stop_distance_pct), 2),
        "close": round(current_close, 2),
    }


def golden_cross_recovery(
    prices: pd.DataFrame,
    short_period: int = 20,
    long_period: int = 200,
    max_distance_pct: float = 10.0,
    crossover_lookback_days: int = 30,
    rising_lookback_days: int = 5,
) -> dict | None:
    """Detect stocks "coming out of correction" via 20 EMA crossing above 200 EMA
    from below, where the crossover is recent and the 20 EMA has not yet run too
    far above the 200 EMA.

    Returns dict with ema values, distance %, days since cross, rising flag.
    Returns None if any condition fails (not above, too extended, no recent
    crossover, or 20 EMA not rising).
    """
    required_bars = long_period + crossover_lookback_days
    if len(prices) < required_bars:
        return None

    close = prices["Close"]
    short_ema = close.ewm(span=short_period, adjust=False).mean()
    long_ema = close.ewm(span=long_period, adjust=False).mean()

    cur_short = float(short_ema.iloc[-1])
    cur_long = float(long_ema.iloc[-1])

    # Must be above (crossed up or in process)
    if cur_short <= cur_long:
        return None

    distance_pct = (cur_short - cur_long) / cur_long * 100
    if distance_pct > max_distance_pct:
        return None  # too extended — no longer "coming out of correction"

    # Confirm recent crossover: at least one bar in lookback window where short <= long
    window_start = max(0, len(short_ema) - crossover_lookback_days)
    lookback_short = short_ema.iloc[window_start:]
    lookback_long = long_ema.iloc[window_start:]
    if not (lookback_short <= lookback_long).any():
        return None  # above for too long; this is a mature uptrend, not a recovery

    # Count days since the most recent "below or equal" bar
    days_since = 0
    for i in range(len(short_ema) - 1, max(0, len(short_ema) - crossover_lookback_days * 2) - 1, -1):
        if short_ema.iloc[i] <= long_ema.iloc[i]:
            break
        days_since += 1

    # 20 EMA must be rising
    if len(short_ema) < rising_lookback_days + 1:
        return None
    past_short = float(short_ema.iloc[-(rising_lookback_days + 1)])
    if cur_short <= past_short:
        return None

    return {
        "short_ema": round(cur_short, 2),
        "long_ema": round(cur_long, 2),
        "distance_pct": round(distance_pct, 2),
        "days_since_cross": int(days_since),
        "close": round(float(close.iloc[-1]), 2),
    }


# ============================================================================
# Support / resistance, break-and-retest, reversal swings
# ============================================================================

def _pivot_points(prices: pd.DataFrame, lookback: int, wing: int) -> list[tuple[float, str]]:
    """Confirmed swing highs/lows in the last `lookback` bars. A pivot needs
    `wing` bars on each side, so the newest `wing` bars can never be pivots."""
    window = prices.iloc[-lookback:]
    highs = window["High"].to_numpy()
    lows = window["Low"].to_numpy()
    pivots: list[tuple[float, str]] = []
    for i in range(wing, len(window) - wing):
        if highs[i] == highs[i - wing:i + wing + 1].max():
            pivots.append((float(highs[i]), "high"))
        if lows[i] == lows[i - wing:i + wing + 1].min():
            pivots.append((float(lows[i]), "low"))
    return pivots


def sr_levels(
    prices: pd.DataFrame, lookback: int = 120, wing: int = 5, cluster_pct: float = 1.5
) -> list[dict]:
    """Cluster pivot highs AND lows into horizontal levels (role reversal: an old
    resistance can act as support). Returns [{level, touches}] sorted by level."""
    if len(prices) < lookback:
        return []
    pivots = sorted(p for p, _ in _pivot_points(prices, lookback, wing))
    clusters: list[list[float]] = []
    for p in pivots:
        if clusters and p <= np.mean(clusters[-1]) * (1 + cluster_pct / 100):
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [{"level": float(np.mean(c)), "touches": len(c)} for c in clusters]


def nearest_support_resistance(
    prices: pd.DataFrame,
    lookback: int = 120,
    wing: int = 5,
    cluster_pct: float = 1.5,
    min_touches: int = 2,
) -> dict:
    """Nearest multi-touch level below and above today's close."""
    close = float(prices["Close"].iloc[-1])
    levels = [lv for lv in sr_levels(prices, lookback, wing, cluster_pct) if lv["touches"] >= min_touches]
    below = [lv for lv in levels if lv["level"] < close]
    above = [lv for lv in levels if lv["level"] > close]
    out: dict = {"close": round(close, 2), "support": None, "resistance": None}
    if below:
        s = max(below, key=lambda lv: lv["level"])
        out["support"] = {"level": round(s["level"], 2), "touches": s["touches"],
                          "distance_pct": round((close - s["level"]) / close * 100, 2)}
    if above:
        r = min(above, key=lambda lv: lv["level"])
        out["resistance"] = {"level": round(r["level"], 2), "touches": r["touches"],
                             "distance_pct": round((r["level"] - close) / close * 100, 2)}
    return out


def recent_breakout_status(
    prices: pd.DataFrame,
    max_age: int = 20,
    level_window: int = 55,
    vol_mult_min: float = 1.5,
    retest_band_pct: float = 2.0,
    fail_pct: float = 3.0,
    min_pullback_pct: float = 3.0,
) -> dict | None:
    """Find the most recent N-day-high breakout (on volume) 1..max_age bars ago
    and classify what price has done since.

    Status:
      "retest"  — pulled back ≥ min_pullback_pct from the post-breakout high,
                  a low in the last 3 bars came within retest_band_pct of the
                  breakout level, and today's close is still at/above the level
                  (within 1%). Classic break-and-retest entry zone.
      "holding" — still above the level, no retest yet.
      None      — no breakout found, or it failed (close > fail_pct below level).
    """
    n = len(prices)
    if n < level_window + max_age + 21:
        return None
    high = prices["High"].to_numpy()
    low = prices["Low"].to_numpy()
    close = prices["Close"].to_numpy()
    vol = prices["Volume"].to_numpy()

    bo_idx = None
    level = None
    for i in range(n - 2, n - 2 - max_age, -1):  # yesterday back to max_age bars ago
        prior_high = high[i - level_window:i].max()
        avg_vol = vol[i - 20:i].mean()
        if close[i] > prior_high and avg_vol > 0 and vol[i] / avg_vol >= vol_mult_min:
            bo_idx, level = i, float(prior_high)
            break
    if bo_idx is None:
        return None

    today_close = float(close[-1])
    if today_close < level * (1 - fail_pct / 100):
        return None  # failed breakout

    post_high = float(high[bo_idx:].max())
    pullback_pct = (post_high - today_close) / post_high * 100
    recent_low = float(low[-3:].min())
    extension_pct = (today_close - level) / level * 100
    age = n - 1 - bo_idx
    bo_vol_mult = float(vol[bo_idx] / vol[bo_idx - 20:bo_idx].mean())

    retested = (
        pullback_pct >= min_pullback_pct
        and recent_low <= level * (1 + retest_band_pct / 100)
        and today_close >= level * 0.99
    )
    status = "retest" if retested else ("holding" if today_close > level else None)
    if status is None:
        return None
    bounce = today_close > float(close[-2])  # green vs prior close = retest bounce confirming

    return {
        "status": status,
        "breakout_level": round(level, 2),
        "breakout_age": int(age),
        "breakout_vol_mult": round(bo_vol_mult, 2),
        "post_high": round(post_high, 2),
        "pullback_pct": round(pullback_pct, 2),
        "extension_pct": round(extension_pct, 2),
        "recent_low": round(recent_low, 2),
        "bounce_today": bool(bounce),
        "close": round(today_close, 2),
    }


def reversal_swing_setup(
    prices: pd.DataFrame,
    min_pullback_pct: float = 5.0,
    max_pullback_pct: float = 25.0,
    rsi_oversold: float = 40.0,
) -> dict | None:
    """Pullback-in-uptrend reversal.

    Requires: close > 200 SMA (long-term uptrend intact), drawdown from the
    20-day high between min and max pullback %, RSI(14) touched ≤ rsi_oversold
    within the last 5 bars, and a bullish reversal candle TODAY:
      - bullish engulfing (prior red, today green, body engulfs prior body)
      - outside reversal (low below prior low, close above prior high)
      - hammer (lower wick ≥ 2× body, close in upper third of range)
    Returns trigger details plus entry / stop / targets, or None.
    """
    if len(prices) < 210:
        return None
    o, h, l, c = (prices[k] for k in ("Open", "High", "Low", "Close"))
    sma200 = float(c.rolling(200).mean().iloc[-1])
    today_c = float(c.iloc[-1])
    if today_c <= sma200:
        return None

    high20 = float(h.iloc[-20:].max())
    pullback = (high20 - float(l.iloc[-5:].min())) / high20 * 100
    if not (min_pullback_pct <= pullback <= max_pullback_pct):
        return None

    rsi_series = rsi(c, 14)
    rsi_min5 = float(rsi_series.iloc[-5:].min())
    rsi_now = float(rsi_series.iloc[-1])
    if rsi_min5 > rsi_oversold:
        return None

    to, th, tl = float(o.iloc[-1]), float(h.iloc[-1]), float(l.iloc[-1])
    po, ph, pl, pc = float(o.iloc[-2]), float(h.iloc[-2]), float(l.iloc[-2]), float(c.iloc[-2])
    rng = th - tl
    body = abs(today_c - to)
    lower_wick = min(today_c, to) - tl

    trigger = None
    if pc < po and today_c > to and today_c >= po and to <= pc:
        trigger = "Bullish engulfing"
    elif tl < pl and today_c > ph:
        trigger = "Outside reversal"
    elif rng > 0 and body > 0 and lower_wick >= 2 * body and (today_c - tl) / rng >= 0.67:
        trigger = "Hammer"
    if trigger is None:
        return None

    stop = float(l.iloc[-5:].min()) * 0.99
    entry = today_c
    risk = entry - stop
    if risk <= 0:
        return None
    sma50 = float(c.rolling(50).mean().iloc[-1])
    near_sma50 = abs(float(l.iloc[-5:].min()) - sma50) / sma50 * 100 <= 2.0

    return {
        "trigger": trigger,
        "pullback_pct": round(pullback, 2),
        "rsi_min5": round(rsi_min5, 1),
        "rsi_now": round(rsi_now, 1),
        "near_sma50": bool(near_sma50),
        "close": round(entry, 2),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "tp1": round(entry + 2 * risk, 2),
        "tp2": round(entry + 3 * risk, 2),
        "high20": round(high20, 2),
    }


def accumulation_day_count(prices: pd.DataFrame, lookback: int = 25, vol_avg_window: int = 20) -> int:
    """Count accumulation days in the last `lookback` sessions.

    An accumulation day = close in upper 25% of day's range AND volume
    above the trailing average. This is the standard IBD definition and
    identifies institutional buying footprints. 5+ in 25 sessions is a
    meaningful accumulation signal.
    """
    if len(prices) < lookback + vol_avg_window:
        return 0
    recent = prices.iloc[-lookback:]
    avg_vol = float(prices["Volume"].iloc[-(lookback + vol_avg_window):-lookback].mean())
    if avg_vol <= 0:
        return 0
    count = 0
    for _, row in recent.iterrows():
        rng = row["High"] - row["Low"]
        if rng <= 0:
            continue
        close_pos = (row["Close"] - row["Low"]) / rng
        if close_pos >= 0.75 and row["Volume"] > avg_vol:
            count += 1
    return int(count)


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
