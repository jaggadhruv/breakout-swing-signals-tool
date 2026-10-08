"""
daily_scan.py

Daily scan for breakout swing trading candidates.

Runs after US market close (~22:00 UTC). Loads the eligible pool from
refresh_universe.py's output, applies trend context and behavioral filters,
detects breakout patterns, scores each setup, computes stops and targets,
computes market breadth, and writes a dated HTML report to reports/.

Cadence: Mon-Fri via GitHub Actions cron.

Inputs:
  eligible_universe.json  (produced by refresh_universe.py)
  data/report_history.json (multi-day streak tracking; created if absent)

Outputs:
  reports/YYYY-MM-DD.html  (the dated report)
  data/report_history.json (updated with today's signals)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

import patterns
import report


# ============================================================================
# Configuration
# ============================================================================

ELIGIBLE_UNIVERSE_PATH = Path("eligible_universe.json")
HISTORY_PATH = Path("data/report_history.json")
SIGNALS_ARCHIVE_PATH = Path("data/signals_archive.json")
WATCHLIST_ARCHIVE_PATH = Path("data/watchlist_archive.json")
SUPERTREND_ARCHIVE_PATH = Path("data/supertrend_archive.json")
REPORTS_DIR = Path("reports")

YFINANCE_DELAY_SECONDS = 0.3
PRICE_HISTORY_PERIOD = "1y"

# Recent-quality section: rolling archive of past signals, filtered by score
ARCHIVE_RETENTION_DAYS = 90
HIGH_QUALITY_THRESHOLD = 60
RECENT_TOP_N = 10

# Watchlist: swing-ready stocks that pass all quality gates but haven't
# triggered a breakout pattern yet. Scored differently from breakouts since
# there's no entry trigger — these are "stalking list" candidates.
WATCHLIST_MIN_SHOW_SCORE = 60       # minimum composite watchlist score to display
WATCHLIST_QUALITY_THRESHOLD = 70    # bar for inclusion in Recent Quality Watchlist history
WATCHLIST_RECENT_TOP_N = 10
ACCUMULATION_LOOKBACK_DAYS = 25     # IBD-style accumulation day count window

# ----------------------------------------------------------------------------
# Elite display filter — strict curation of "today" sections
# ----------------------------------------------------------------------------
# Both archives (signals + watchlist) still record EVERYTHING that passes the
# base gates, so Recent Quality sections keep building 90 days of history.
# The elite filter only applies to the two "today" sections on each report.
# Rationale: avoid reviewing 20+ names daily; focus on the highest-confluence
# handful. Historical quality lists let you still see broader context.

MAX_BREAKOUTS_SHOWN         = 5     # hard cap on Today's Breakouts rows
MAX_WATCHLIST_SHOWN         = 8     # hard cap on Today's Watchlist rows

ELITE_RS_PERCENTILE_MIN     = 85    # top 15% of universe (vs base gate of 75)
ELITE_MOMENTUM_PASSES_MIN   = 4     # all 4 momentum checks (vs base gate of 3)
ELITE_SECTOR_RANK_MAX       = 4     # top 4 sectors only (vs base gate of 6)
ELITE_WATCHLIST_MIN_ACC_DAYS = 5    # watchlist entries need 5+ accumulation days

# ----------------------------------------------------------------------------
# Supertrend (daily chart) — trend-following signal, parameters match the
# weekly Positional Trading Tool so the two stay consistent.
# ----------------------------------------------------------------------------
SUPERTREND_ATR_PERIOD        = 10   # matches TradingView free tier
SUPERTREND_MULTIPLIER        = 2.5  # matches TradingView free tier
SUPERTREND_MIN_SHOW_SCORE    = 60   # minimum composite to display
SUPERTREND_QUALITY_THRESHOLD = 70   # bar for history inclusion
SUPERTREND_RECENT_TOP_N      = 10   # top N in Recent Quality Supertrend
MAX_SUPERTREND_SHOWN         = 6    # hard cap on today's section

# Layer 4: trend context filter — a stock passes if all four hold
TREND_ABOVE_50_SMA = True
TREND_ABOVE_200_SMA = True
TREND_200_SMA_RISING = True
TREND_MAX_DISTANCE_FROM_52W_HIGH_PCT = 0.25   # within 25% of 52-week high

# Layer 5: behavioral filter
BEHAVIORAL_MAX_GAP_DOWN_PCT = -10.0            # exclude if any -10% gap in last 20 sessions
# Earnings-in-next-10-days filter: OFF by default. yfinance's earnings_dates
# is unreliable and adds ~1 extra network call per ticker (doubles scan time).
# Enable if you want the extra check; add your own delay if you hit rate limits.
ENABLE_EARNINGS_CHECK = False
EARNINGS_LOOKAHEAD_DAYS = 10

# Setup scoring
SCORING = {
    "n_week_20":              10,
    "n_week_55":              20,
    "n_week_252":             30,
    "horizontal_resistance":  25,
    "volatility_contraction": 25,
    "vol_bonus_slope":        10,      # (vol_mult - 1.5) * slope, capped
    "vol_bonus_cap":          15,
    "base_length_divisor":    5,       # days_in_consolidation / divisor, capped
    "base_length_cap":        10,
    "piotroski_multiplier":   2,       # piotroski * multiplier, capped
    "piotroski_cap":          18,
    "trend_context_bonus":    10,      # if 200 SMA rising AND close within 15% of 52w high
    "streak_per_day":         5,
    "streak_cap":             15,
    "rs_elite_bonus":         10,      # if ticker RS percentile >= 90
    "sector_top3_bonus":      5,       # if ticker's sector ranks top 3 of 11
    "momentum_full_bonus":    5,       # if all 4 momentum confluence checks pass
    "min_show_score":         40,
    "min_show_score_adverse": 75,      # raised bar when market breadth is Adverse
}

# ----------------------------------------------------------------------------
# Confluence layer thresholds
# ----------------------------------------------------------------------------

# Momentum confluence: RSI in-range, ADX trending, weekly MACD positive,
# price in upper 40% of 52W range. Require this many of 4 to pass.
MOMENTUM_MIN_PASS           = 3
MOMENTUM_RSI_MIN            = 50
MOMENTUM_RSI_MAX            = 75
MOMENTUM_ADX_MIN            = 20
MOMENTUM_RANGE_POSITION_MIN = 0.60  # top 40% of 52w range

# Relative strength percentile gate (vs eligible pool, 12-week return)
RS_LOOKBACK_WEEKS      = 12
RS_PERCENTILE_MIN      = 75   # top 25% of universe
RS_PERCENTILE_ELITE    = 90   # top 10% gets scoring bonus

# Sector regime gating via Sector SPDR ETFs
SECTOR_GATING_ENABLED  = True
SECTOR_RS_LOOKBACK_DAYS = 60
SECTOR_MAX_RANK        = 6   # only tickers in top 6 of 11 sectors
SECTOR_TOP_RANK        = 3   # top 3 sectors get scoring bonus

# Market regime gate (uses weekly breadth score)
BREADTH_ADVERSE_THRESHOLD = 4.0

# Sector SPDR ETFs — one per GICS sector
SECTOR_ETFS = {
    "XLK":  "Technology",
    "XLV":  "Health Care",
    "XLF":  "Financials",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLI":  "Industrials",
    "XLE":  "Energy",
    "XLU":  "Utilities",
    "XLB":  "Materials",
    "XLRE": "Real Estate",
    "XLC":  "Communication Services",
}

# Map screener sector labels → ETF ticker. Covers common variants from
# Finviz, Stockanalysis, GICS. Lowercase match.
SECTOR_TO_ETF = {
    "technology": "XLK",
    "information technology": "XLK",
    "tech": "XLK",
    "health care": "XLV",
    "healthcare": "XLV",
    "financial": "XLF",
    "financials": "XLF",
    "financial services": "XLF",
    "consumer discretionary": "XLY",
    "consumer cyclical": "XLY",
    "consumer staples": "XLP",
    "consumer defensive": "XLP",
    "industrials": "XLI",
    "industrial": "XLI",
    "energy": "XLE",
    "utilities": "XLU",
    "basic materials": "XLB",
    "materials": "XLB",
    "real estate": "XLRE",
    "communication services": "XLC",
    "communications": "XLC",
}

# Stops and targets
STOP_PCT_BELOW_BREAKOUT = 0.07     # min(breakout * (1 - 0.07), 20-day swing low)
STOP_SWING_LOW_LOOKBACK = 20
TP1_R_MULTIPLE = 2.0
TP2_R_MULTIPLE = 3.0

# Market breadth score construction
BREADTH_ROC_LOOKBACK_DAYS = 14

# Report history retention
HISTORY_RETENTION_DAYS = 14

# Market index and volatility symbols
SPY_SYMBOL = "SPY"
VIX_SYMBOL = "^VIX"


# ============================================================================
# Utilities
# ============================================================================

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_eligible_universe() -> dict:
    if not ELIGIBLE_UNIVERSE_PATH.exists():
        sys.exit(
            f"ERROR: {ELIGIBLE_UNIVERSE_PATH} not found. "
            "Run refresh_universe.py first."
        )
    return json.loads(ELIGIBLE_UNIVERSE_PATH.read_text())


def fetch_prices(ticker: str, period: str = PRICE_HISTORY_PERIOD) -> pd.DataFrame | None:
    """Fetch OHLCV. Drops the last bar if its volume looks incomplete
    (protects against manual runs during US trading hours — the intraday
    bar has ~10-30% of normal volume and would break the pattern-detection
    volume filter otherwise)."""
    try:
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        if hist is None or hist.empty or len(hist) < 60:
            return None
        # Partial-day guard: if the most recent bar has less than 30% of the
        # prior 20-day average volume, treat it as an incomplete session and
        # drop it. Scan will then use the last complete trading day.
        if len(hist) >= 22:
            avg_vol_20d = float(hist["Volume"].iloc[-21:-1].mean())
            last_vol = float(hist["Volume"].iloc[-1])
            if avg_vol_20d > 0 and last_vol < avg_vol_20d * 0.30:
                hist = hist.iloc[:-1]
        if len(hist) < 60:
            return None
        return hist
    except Exception:
        return None


# ============================================================================
# Layer 4: Trend context filter
# ============================================================================

def passes_trend_filter(prices: pd.DataFrame, spy: pd.DataFrame) -> tuple[bool, dict]:
    """All four trend conditions must hold."""
    ctx = {}
    close_now = float(prices["Close"].iloc[-1])

    sma_50 = patterns.sma(prices["Close"], 50)
    sma_200 = patterns.sma(prices["Close"], 200)
    if sma_50.isna().iloc[-1] or sma_200.isna().iloc[-1]:
        return False, ctx

    above_50 = close_now > float(sma_50.iloc[-1])
    above_200 = close_now > float(sma_200.iloc[-1])
    sma_200_rising = patterns.is_sma_rising(sma_200, lookback=20)
    high_prox = patterns.high_52w_proximity(prices)
    near_52w = high_prox is not None and (1 - high_prox) <= TREND_MAX_DISTANCE_FROM_52W_HIGH_PCT

    ctx = {
        "above_50_sma": above_50,
        "above_200_sma": above_200,
        "sma_200_rising": sma_200_rising,
        "high_52w_proximity": round(high_prox, 3) if high_prox else None,
        "rs_12w_vs_spy_pct": patterns.relative_strength_pct(prices, spy, 12),
        "rs_26w_vs_spy_pct": patterns.relative_strength_pct(prices, spy, 26),
    }

    passes = (
        (not TREND_ABOVE_50_SMA or above_50)
        and (not TREND_ABOVE_200_SMA or above_200)
        and (not TREND_200_SMA_RISING or sma_200_rising)
        and near_52w
    )
    return passes, ctx


# ============================================================================
# Layer 5: Behavioral filter
# ============================================================================

def _has_earnings_soon(ticker: str) -> bool:
    """Best-effort check via yfinance.earnings_dates.
    Returns True only if we're confident earnings are within lookahead window.
    On any uncertainty (empty data, exceptions), returns False to keep the stock in.
    """
    try:
        edates = yf.Ticker(ticker).earnings_dates
        if edates is None or edates.empty:
            return False
        now = pd.Timestamp.now(tz=edates.index.tz) if edates.index.tz else pd.Timestamp.now()
        horizon = now + pd.Timedelta(days=EARNINGS_LOOKAHEAD_DAYS)
        upcoming = edates[(edates.index >= now) & (edates.index <= horizon)]
        return not upcoming.empty
    except Exception:
        return False


def passes_behavioral_filter(prices: pd.DataFrame, ticker: str) -> tuple[bool, dict]:
    worst_gap = patterns.worst_recent_gap_down_pct(prices)
    earnings_soon = _has_earnings_soon(ticker) if ENABLE_EARNINGS_CHECK else False
    ctx = {"worst_gap_down_pct_20d": round(worst_gap, 2), "earnings_within_10d": earnings_soon}
    passes = (worst_gap > BEHAVIORAL_MAX_GAP_DOWN_PCT) and (not earnings_soon)
    return passes, ctx


# ============================================================================
# Confluence layer: momentum, relative strength, sector regime
# ============================================================================

def passes_momentum_confluence(prices: pd.DataFrame) -> tuple[bool, dict]:
    """4-check momentum confluence. Returns (bool, dict of per-check results).

    Pass requires >= MOMENTUM_MIN_PASS of 4:
      1. RSI(14) in [50, 75] range (strong but not extended)
      2. ADX(14) >= 20 (actually trending)
      3. Weekly MACD histogram > 0 (higher-timeframe alignment)
      4. Price in top 40% of 52-week range (already in strength)
    """
    checks = {"rsi": False, "adx": False, "weekly_macd": False, "range_pos": False}

    # RSI
    try:
        rsi_series = patterns.rsi(prices["Close"], 14)
        rsi_val = float(rsi_series.iloc[-1])
        checks["rsi"] = MOMENTUM_RSI_MIN <= rsi_val <= MOMENTUM_RSI_MAX
    except Exception:
        rsi_val = None

    # ADX
    try:
        adx_series = patterns.adx(prices, 14)
        adx_val = float(adx_series.iloc[-1])
        checks["adx"] = adx_val >= MOMENTUM_ADX_MIN
    except Exception:
        adx_val = None

    # Weekly MACD histogram
    try:
        weekly_closes = prices["Close"].resample("W").last().dropna()
        if len(weekly_closes) >= 30:
            _, _, hist = patterns.macd(weekly_closes)
            hist_val = float(hist.iloc[-1])
            checks["weekly_macd"] = hist_val > 0
        else:
            hist_val = None
    except Exception:
        hist_val = None

    # 52-week range position
    range_pos = patterns.range_position_52w(prices)
    checks["range_pos"] = (range_pos is not None and range_pos >= MOMENTUM_RANGE_POSITION_MIN)

    pass_count = sum(checks.values())
    ctx = {
        "checks": checks,
        "pass_count": pass_count,
        "rsi_14": round(rsi_val, 2) if rsi_val is not None else None,
        "adx_14": round(adx_val, 2) if adx_val is not None else None,
        "weekly_macd_hist": round(hist_val, 4) if hist_val is not None else None,
        "range_position_52w": round(range_pos, 3) if range_pos is not None else None,
    }
    return pass_count >= MOMENTUM_MIN_PASS, ctx


def compute_ticker_rs(stock: pd.DataFrame, spy: pd.DataFrame) -> float | None:
    """Stock total return minus SPY total return over RS_LOOKBACK_WEEKS."""
    sessions = RS_LOOKBACK_WEEKS * 5
    if len(stock) < sessions + 1 or len(spy) < sessions + 1:
        return None
    stock_ret = float(stock["Close"].iloc[-1] / stock["Close"].iloc[-(sessions + 1)] - 1)
    spy_ret = float(spy["Close"].iloc[-1] / spy["Close"].iloc[-(sessions + 1)] - 1)
    return (stock_ret - spy_ret) * 100


def compute_rs_percentiles(ticker_rs: dict[str, float]) -> dict[str, float]:
    """Convert raw RS values to percentile ranks (0-100) across the universe."""
    valid = {t: v for t, v in ticker_rs.items() if v is not None}
    if not valid:
        return {}
    sorted_items = sorted(valid.items(), key=lambda kv: kv[1])
    n = len(sorted_items)
    if n == 1:
        return {sorted_items[0][0]: 50.0}
    return {t: round(100.0 * i / (n - 1), 1) for i, (t, _) in enumerate(sorted_items)}


def fetch_sector_etfs() -> dict[str, pd.DataFrame]:
    """Fetch prices for all 11 Sector SPDR ETFs."""
    etfs: dict[str, pd.DataFrame] = {}
    for ticker in SECTOR_ETFS:
        prices = fetch_prices(ticker, period="6mo")
        if prices is not None:
            etfs[ticker] = prices
        time.sleep(YFINANCE_DELAY_SECONDS)
    return etfs


def compute_sector_rs(sector_etfs: dict[str, pd.DataFrame], spy: pd.DataFrame) -> dict[str, float]:
    """Return {etf_ticker: 60-day return minus SPY 60-day return} in percent."""
    if spy is None or len(spy) < SECTOR_RS_LOOKBACK_DAYS + 1:
        return {}
    spy_ret = float(spy["Close"].iloc[-1] / spy["Close"].iloc[-(SECTOR_RS_LOOKBACK_DAYS + 1)] - 1)
    out: dict[str, float] = {}
    for etf, prices in sector_etfs.items():
        if prices is None or len(prices) < SECTOR_RS_LOOKBACK_DAYS + 1:
            continue
        etf_ret = float(prices["Close"].iloc[-1] / prices["Close"].iloc[-(SECTOR_RS_LOOKBACK_DAYS + 1)] - 1)
        out[etf] = round((etf_ret - spy_ret) * 100, 2)
    return out


def rank_sectors(sector_rs: dict[str, float]) -> dict[str, int]:
    """Rank ETFs 1 (strongest) to N (weakest) by RS."""
    if not sector_rs:
        return {}
    sorted_etfs = sorted(sector_rs.items(), key=lambda kv: kv[1], reverse=True)
    return {etf: rank + 1 for rank, (etf, _) in enumerate(sorted_etfs)}


def sector_etf_for(sector_label: str) -> str | None:
    """Map a free-text sector label (from the CSV) to an ETF ticker. None if unknown."""
    if not sector_label:
        return None
    return SECTOR_TO_ETF.get(sector_label.strip().lower())


def passes_sector_gate(sector_label: str, sector_ranks: dict[str, int]) -> tuple[bool, int | None]:
    """True if ticker's sector ranks <= SECTOR_MAX_RANK. Unmapped sectors pass."""
    etf = sector_etf_for(sector_label)
    if etf is None:
        return True, None  # don't gate what we can't measure
    rank = sector_ranks.get(etf)
    if rank is None:
        return True, None
    return rank <= SECTOR_MAX_RANK, rank


# ============================================================================
# Setup scoring
# ============================================================================

def compute_score(
    patterns_result: dict,
    piotroski: int | None,
    trend_ctx: dict,
    days_in_consolidation: int,
    days_on_report: int,
    *,
    rs_percentile: float | None = None,
    sector_rank: int | None = None,
    momentum_pass_count: int = 0,
) -> tuple[float, dict]:
    """Composite 0-100+ score with confluence bonuses. Returns (score, breakdown)."""
    breakdown = {}
    total = 0.0

    # Pattern base points (summed if multiple triggered)
    for key in ("n_week_20", "n_week_55", "n_week_252",
                "horizontal_resistance", "volatility_contraction"):
        if patterns_result[key]["triggered"]:
            pts = SCORING[key]
            breakdown[key] = pts
            total += pts

    # Volume bonus (use the max volume multiple across triggered patterns)
    vol_mults = [
        p["volume_multiple"]
        for p in patterns_result.values()
        if p.get("triggered") and "volume_multiple" in p
    ]
    if vol_mults:
        max_vol = max(vol_mults)
        vol_bonus = min((max_vol - 1.5) * SCORING["vol_bonus_slope"], SCORING["vol_bonus_cap"])
        vol_bonus = max(0, vol_bonus)
        breakdown["volume_bonus"] = round(vol_bonus, 1)
        total += vol_bonus

    # Base length bonus
    base_bonus = min(days_in_consolidation / SCORING["base_length_divisor"], SCORING["base_length_cap"])
    breakdown["base_length_bonus"] = round(base_bonus, 1)
    total += base_bonus

    # Piotroski bonus
    if piotroski is not None:
        p_bonus = min(piotroski * SCORING["piotroski_multiplier"], SCORING["piotroski_cap"])
        breakdown["piotroski_bonus"] = round(p_bonus, 1)
        total += p_bonus

    # Trend-context bonus (only if 200 SMA rising AND close within 15% of 52W high)
    hp = trend_ctx.get("high_52w_proximity")
    if trend_ctx.get("sma_200_rising") and hp is not None and hp >= 0.85:
        breakdown["trend_context_bonus"] = SCORING["trend_context_bonus"]
        total += SCORING["trend_context_bonus"]

    # Multi-day streak bonus
    if days_on_report > 1:
        streak_bonus = min((days_on_report - 1) * SCORING["streak_per_day"], SCORING["streak_cap"])
        breakdown["streak_bonus"] = streak_bonus
        total += streak_bonus

    # Confluence bonuses
    if rs_percentile is not None and rs_percentile >= RS_PERCENTILE_ELITE:
        breakdown["rs_elite_bonus"] = SCORING["rs_elite_bonus"]
        total += SCORING["rs_elite_bonus"]
    if sector_rank is not None and sector_rank <= SECTOR_TOP_RANK:
        breakdown["sector_top3_bonus"] = SCORING["sector_top3_bonus"]
        total += SCORING["sector_top3_bonus"]
    if momentum_pass_count >= 4:
        breakdown["momentum_full_bonus"] = SCORING["momentum_full_bonus"]
        total += SCORING["momentum_full_bonus"]

    return round(total, 1), breakdown


# ============================================================================
# Stops and targets
# ============================================================================

def compute_stop_and_targets(prices: pd.DataFrame, patterns_result: dict) -> dict:
    """Stop = the TIGHTER of (breakout * 0.93) and (20-day swing low).

    Rationale: 7% below the breakout is a hard risk cap; the swing low is used
    if it sits ABOVE that level (tighter stop, better R:R). If the swing low
    is far below breakout, we ignore it — a 15%+ stop is too much risk for a
    swing trade. TPs at 2R and 3R off entry (current close).
    """
    close_now = float(prices["Close"].iloc[-1])
    # Prefer the highest triggered breakout level as reference
    breakout_levels = []
    for p in patterns_result.values():
        if not p.get("triggered"):
            continue
        for key in ("breakout_level", "resistance_level", "range_high"):
            if key in p:
                breakout_levels.append(p[key])
    breakout_level = max(breakout_levels) if breakout_levels else close_now

    stop_pct = breakout_level * (1 - STOP_PCT_BELOW_BREAKOUT)
    swing_low_val = patterns.swing_low(prices, STOP_SWING_LOW_LOOKBACK) or stop_pct
    # Take the tighter (higher) of the two — caps risk while respecting a tight base
    stop = max(stop_pct, swing_low_val)
    # Guard: stop must be strictly below current close
    if stop >= close_now:
        stop = close_now * (1 - STOP_PCT_BELOW_BREAKOUT)

    risk = close_now - stop
    tp1 = close_now + TP1_R_MULTIPLE * risk
    tp2 = close_now + TP2_R_MULTIPLE * risk

    return {
        "entry": round(close_now, 2),
        "stop": round(stop, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "breakout_level_used": round(breakout_level, 2),
    }


# ============================================================================
# Watchlist — swing-ready stocks without a fired pattern
# ============================================================================

def compute_watchlist_setup(prices: pd.DataFrame, lookback: int = 20) -> dict | None:
    """Compute the pending breakout setup for a watchlist ticker.

    Trigger = nearest resistance (20-day high; falls back to 55-day if already
    above). Stop = tighter of (trigger × 0.93) or 20-day swing low. TPs at 2R
    and 3R from the pending trigger. Returns None if we can't locate a sensible
    trigger above current price.
    """
    if len(prices) < 60:
        return None
    close_now = float(prices["Close"].iloc[-1])

    trigger = float(prices["High"].iloc[-(lookback + 1):-1].max())
    if trigger <= close_now:
        # Already above 20-day high — try 55-day as the next natural resistance
        trigger = float(prices["High"].iloc[-(55 + 1):-1].max())
        if trigger <= close_now:
            return None  # trading above all nearby resistance; no clean pending trigger

    swing_low = float(prices["Low"].iloc[-lookback:].min())
    stop = max(trigger * 0.93, swing_low)
    if stop >= trigger:
        stop = trigger * 0.93
    risk = trigger - stop
    pct_to_trigger = (trigger - close_now) / close_now * 100

    return {
        "current": round(close_now, 2),
        "trigger": round(trigger, 2),
        "stop_pending": round(stop, 2),
        "tp1_pending": round(trigger + 2 * risk, 2),
        "tp2_pending": round(trigger + 3 * risk, 2),
        "pct_to_trigger": round(pct_to_trigger, 2),
    }


def compute_watchlist_score(
    *,
    rs_percentile: float | None,
    momentum_passes: int,
    sector_rank: int | None,
    accumulation_days: int,
    range_52w_position: float | None,
) -> tuple[float, dict]:
    """Composite watchlist quality score (0 to ~112).

    Weights:
      RS strength         up to 50 (rs_percentile / 2)
      Momentum confluence up to 20 (5 per check passed)
      Sector strength     up to 12 (based on rank 1-7)
      Accumulation days   up to 20 (2 per day, cap 10 days)
      52W position bonus      +10 if ≥ 75% up the range
    """
    breakdown = {}
    total = 0.0

    if rs_percentile is not None:
        pts = round(rs_percentile / 2, 1)
        breakdown["rs_strength"] = pts
        total += pts

    mom_pts = momentum_passes * 5
    breakdown["momentum"] = mom_pts
    total += mom_pts

    if sector_rank is not None and sector_rank <= 7:
        sec_pts = (8 - sector_rank) * 2
        # Rank 1 -> 14, rank 7 -> 2. Clamp at 12 for consistency.
        sec_pts = min(sec_pts, 12)
        breakdown["sector_strength"] = sec_pts
        total += sec_pts

    acc_pts = min(accumulation_days, 10) * 2
    breakdown["accumulation"] = acc_pts
    total += acc_pts

    if range_52w_position is not None and range_52w_position >= 0.75:
        breakdown["range_52w_bonus"] = 10
        total += 10

    return round(total, 1), breakdown


# ============================================================================
# Watchlist archive (parallel to signals_archive)
# ============================================================================

def load_watchlist_archive() -> list[dict]:
    if not WATCHLIST_ARCHIVE_PATH.exists():
        return []
    try:
        data = json.loads(WATCHLIST_ARCHIVE_PATH.read_text())
        return data.get("watchlist", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_watchlist_archive(archive: list[dict]) -> None:
    WATCHLIST_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_ARCHIVE_PATH.write_text(json.dumps({"watchlist": archive}, indent=2))


def update_watchlist_archive(
    archive: list[dict], todays_watchlist: list[dict], today_str: str
) -> list[dict]:
    cutoff = (
        datetime.utcnow() - timedelta(days=ARCHIVE_RETENTION_DAYS)
    ).strftime("%Y-%m-%d")
    archive = [
        s for s in archive
        if s.get("date", "") >= cutoff and s.get("date") != today_str
    ]
    for w in todays_watchlist:
        archive.append({
            "date": today_str,
            "ticker": w["ticker"],
            "name": w.get("name", ""),
            "sector": w.get("sector", "Unknown"),
            "sector_rank": w.get("sector_rank"),
            "watchlist_score": w["watchlist_score"],
            "rs_percentile": w.get("rs_percentile"),
            "momentum_passes": w.get("momentum_passes", 0),
            "accumulation_days": w.get("accumulation_days", 0),
            "range_52w_position": w.get("range_52w_position"),
            "current": w.get("current"),
            "trigger": w.get("trigger"),
            "stop_pending": w.get("stop_pending"),
            "tp1_pending": w.get("tp1_pending"),
            "tp2_pending": w.get("tp2_pending"),
            "pct_to_trigger": w.get("pct_to_trigger"),
            "piotroski": w.get("piotroski"),
        })
    return archive


def compute_recent_quality_watchlist(archive: list[dict], n: int = WATCHLIST_RECENT_TOP_N) -> list[dict]:
    """Composite-ranked top N unique watchlist tickers from the archive.

    Only tickers whose best watchlist_score ever met WATCHLIST_QUALITY_THRESHOLD
    are eligible. Uses the same recency + appearance + accumulation weighting
    philosophy as compute_recent_high_quality, adapted for watchlist fields.
    """
    if not archive:
        return []

    today = datetime.utcnow().date()
    by_ticker: dict[str, dict] = {}
    for s in archive:
        t = s.get("ticker")
        if not t:
            continue
        score = float(s.get("watchlist_score", 0))
        date_str = s.get("date", "")

        if t not in by_ticker:
            by_ticker[t] = {
                "ticker": t,
                "name": s.get("name", ""),
                "sector": s.get("sector", "Unknown"),
                "sector_rank": s.get("sector_rank"),
                "best_score": score,
                "best_score_date": date_str,
                "peak_current": s.get("current"),
                "peak_trigger": s.get("trigger"),
                "peak_stop_pending": s.get("stop_pending"),
                "peak_tp1_pending": s.get("tp1_pending"),
                "peak_tp2_pending": s.get("tp2_pending"),
                "peak_pct_to_trigger": s.get("pct_to_trigger"),
                "peak_rs_percentile": s.get("rs_percentile"),
                "peak_momentum_passes": s.get("momentum_passes", 0),
                "peak_accumulation_days": s.get("accumulation_days", 0),
                "piotroski": s.get("piotroski"),
                "appearances": 1,
                "latest_date": date_str,
            }
        else:
            agg = by_ticker[t]
            agg["appearances"] += 1
            if date_str > agg["latest_date"]:
                agg["latest_date"] = date_str
            if score > agg["best_score"]:
                agg["best_score"] = score
                agg["best_score_date"] = date_str
                agg["peak_current"] = s.get("current")
                agg["peak_trigger"] = s.get("trigger")
                agg["peak_stop_pending"] = s.get("stop_pending")
                agg["peak_tp1_pending"] = s.get("tp1_pending")
                agg["peak_tp2_pending"] = s.get("tp2_pending")
                agg["peak_pct_to_trigger"] = s.get("pct_to_trigger")
                agg["peak_rs_percentile"] = s.get("rs_percentile")
                agg["peak_momentum_passes"] = s.get("momentum_passes", 0)
                agg["peak_accumulation_days"] = s.get("accumulation_days", 0)
                if s.get("piotroski") is not None:
                    agg["piotroski"] = s.get("piotroski")

    eligible = [c for c in by_ticker.values() if c["best_score"] >= WATCHLIST_QUALITY_THRESHOLD]

    for c in eligible:
        try:
            latest = datetime.strptime(c["latest_date"], "%Y-%m-%d").date()
            days_since = (today - latest).days
        except (ValueError, TypeError):
            days_since = 999

        if days_since <= 7:
            recency = 15
        elif days_since <= 21:
            recency = 5
        else:
            recency = 0

        appearance_bonus = min(c["appearances"] * 2, 15)
        acc_bonus = min(c["peak_accumulation_days"], 10)

        c["keep_score"] = round(c["best_score"] + recency + appearance_bonus + acc_bonus, 1)

    eligible.sort(key=lambda c: c["keep_score"], reverse=True)
    return eligible[:n]


# ============================================================================
# Supertrend — daily chart, long state detection + scoring + archive
# ============================================================================

def compute_supertrend_score(
    *,
    st_state: dict,
    rs_percentile: float | None,
    momentum_passes: int,
    sector_rank: int | None,
    accumulation_days: int,
) -> tuple[float, dict]:
    """Composite Supertrend-long quality score (0 to ~122).

    Fresher flips are worth more (recent entries have the longest runway).
    Weights:
      Flip recency           up to 30 (today=30, 1-3d=25, 4-7d=15, 8-15d=5)
      RS strength            up to 50 (rs_percentile ÷ 2)
      Momentum confluence    up to 20 (5 per check passed)
      Sector strength        up to 12 (based on rank 1-7)
      Accumulation days      up to 10 (1 per day, cap at 10)
    """
    breakdown: dict = {}
    total = 0.0

    days_since = st_state.get("days_since_flip", 999)
    if days_since <= 1:
        recency = 30
    elif days_since <= 3:
        recency = 25
    elif days_since <= 7:
        recency = 15
    elif days_since <= 15:
        recency = 5
    else:
        recency = 0
    breakdown["flip_recency"] = recency
    total += recency

    if rs_percentile is not None:
        pts = round(rs_percentile / 2, 1)
        breakdown["rs_strength"] = pts
        total += pts

    mom_pts = momentum_passes * 5
    breakdown["momentum"] = mom_pts
    total += mom_pts

    if sector_rank is not None and sector_rank <= 7:
        sec_pts = (8 - sector_rank) * 2
        sec_pts = min(sec_pts, 12)
        breakdown["sector_strength"] = sec_pts
        total += sec_pts

    acc_pts = min(accumulation_days, 10)
    breakdown["accumulation"] = acc_pts
    total += acc_pts

    return round(total, 1), breakdown


def load_supertrend_archive() -> list[dict]:
    if not SUPERTREND_ARCHIVE_PATH.exists():
        return []
    try:
        data = json.loads(SUPERTREND_ARCHIVE_PATH.read_text())
        return data.get("supertrend", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_supertrend_archive(archive: list[dict]) -> None:
    SUPERTREND_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUPERTREND_ARCHIVE_PATH.write_text(json.dumps({"supertrend": archive}, indent=2))


def update_supertrend_archive(
    archive: list[dict], todays_entries: list[dict], today_str: str
) -> list[dict]:
    cutoff = (
        datetime.utcnow() - timedelta(days=ARCHIVE_RETENTION_DAYS)
    ).strftime("%Y-%m-%d")
    archive = [
        s for s in archive
        if s.get("date", "") >= cutoff and s.get("date") != today_str
    ]
    for e in todays_entries:
        archive.append({
            "date": today_str,
            "ticker": e["ticker"],
            "name": e.get("name", ""),
            "sector": e.get("sector", "Unknown"),
            "sector_rank": e.get("sector_rank"),
            "supertrend_score": e["supertrend_score"],
            "rs_percentile": e.get("rs_percentile"),
            "momentum_passes": e.get("momentum_passes", 0),
            "accumulation_days": e.get("accumulation_days", 0),
            "close": e.get("close"),
            "supertrend_level": e.get("supertrend_level"),
            "stop_distance_pct": e.get("stop_distance_pct"),
            "days_since_flip": e.get("days_since_flip"),
            "piotroski": e.get("piotroski"),
        })
    return archive


def compute_recent_quality_supertrend(archive: list[dict], n: int = SUPERTREND_RECENT_TOP_N) -> list[dict]:
    """Composite-ranked top N unique Supertrend-long tickers from the archive.

    Only tickers whose peak supertrend_score ever met SUPERTREND_QUALITY_THRESHOLD
    are eligible. Keep score adds recency, appearance, and accumulation bonuses.
    """
    if not archive:
        return []

    today = datetime.utcnow().date()
    by_ticker: dict[str, dict] = {}
    for s in archive:
        t = s.get("ticker")
        if not t:
            continue
        score = float(s.get("supertrend_score", 0))
        date_str = s.get("date", "")

        if t not in by_ticker:
            by_ticker[t] = {
                "ticker": t,
                "name": s.get("name", ""),
                "sector": s.get("sector", "Unknown"),
                "sector_rank": s.get("sector_rank"),
                "best_score": score,
                "best_score_date": date_str,
                "peak_close": s.get("close"),
                "peak_supertrend_level": s.get("supertrend_level"),
                "peak_stop_distance_pct": s.get("stop_distance_pct"),
                "peak_days_since_flip": s.get("days_since_flip"),
                "peak_rs_percentile": s.get("rs_percentile"),
                "peak_momentum_passes": s.get("momentum_passes", 0),
                "peak_accumulation_days": s.get("accumulation_days", 0),
                "piotroski": s.get("piotroski"),
                "appearances": 1,
                "latest_date": date_str,
            }
        else:
            agg = by_ticker[t]
            agg["appearances"] += 1
            if date_str > agg["latest_date"]:
                agg["latest_date"] = date_str
            if score > agg["best_score"]:
                agg["best_score"] = score
                agg["best_score_date"] = date_str
                agg["peak_close"] = s.get("close")
                agg["peak_supertrend_level"] = s.get("supertrend_level")
                agg["peak_stop_distance_pct"] = s.get("stop_distance_pct")
                agg["peak_days_since_flip"] = s.get("days_since_flip")
                agg["peak_rs_percentile"] = s.get("rs_percentile")
                agg["peak_momentum_passes"] = s.get("momentum_passes", 0)
                agg["peak_accumulation_days"] = s.get("accumulation_days", 0)
                if s.get("piotroski") is not None:
                    agg["piotroski"] = s.get("piotroski")

    eligible = [c for c in by_ticker.values() if c["best_score"] >= SUPERTREND_QUALITY_THRESHOLD]

    for c in eligible:
        try:
            latest = datetime.strptime(c["latest_date"], "%Y-%m-%d").date()
            days_since = (today - latest).days
        except (ValueError, TypeError):
            days_since = 999

        if days_since <= 7:
            recency = 15
        elif days_since <= 21:
            recency = 5
        else:
            recency = 0

        appearance_bonus = min(c["appearances"] * 2, 15)
        acc_bonus = min(c["peak_accumulation_days"], 10)
        c["keep_score"] = round(c["best_score"] + recency + appearance_bonus + acc_bonus, 1)

    eligible.sort(key=lambda c: c["keep_score"], reverse=True)
    return eligible[:n]


# ============================================================================
# Market breadth
# ============================================================================

def _normalize_pct_above_sma(pct: float) -> float:
    """0% -> 0, 100% -> 10. Linear."""
    return max(0.0, min(10.0, pct / 10.0))


def _normalize_high_low_ratio(new_highs: int, new_lows: int) -> float:
    """Ratio-based: 5:1 highs>lows -> 10, 1:1 -> 5, 1:5 -> 0."""
    if new_highs + new_lows == 0:
        return 5.0
    share = new_highs / (new_highs + new_lows)
    # share of 0.5 = 5, share of 0.83 (5:1) = 10, share of 0.17 (1:5) = 0
    return max(0.0, min(10.0, (share - 0.17) / (0.83 - 0.17) * 10))


def _normalize_spy_roc(roc_pct: float) -> float:
    """-5% -> 0, 0 -> 5, +5% -> 10. Linear, clamped."""
    return max(0.0, min(10.0, 5.0 + roc_pct))


def _normalize_vix(vix_level: float) -> float:
    """Inverted: 10 -> 10, 40 -> 0."""
    return max(0.0, min(10.0, (40.0 - vix_level) / 3.0))


def compute_market_breadth(
    eligible_price_cache: dict[str, pd.DataFrame],
    spy: pd.DataFrame,
    vix: pd.DataFrame,
    history: dict,
) -> dict:
    """Weekly (today) + monthly (4-week avg) breadth on a 0-10 scale."""
    # % above 200 / 50 SMA
    above_200_count = 0
    above_50_count = 0
    new_highs = 0
    new_lows = 0
    total = 0

    for ticker, prices in eligible_price_cache.items():
        if prices is None or len(prices) < 200:
            continue
        total += 1
        close_now = float(prices["Close"].iloc[-1])
        sma_50 = patterns.sma(prices["Close"], 50).iloc[-1]
        sma_200 = patterns.sma(prices["Close"], 200).iloc[-1]
        if pd.notna(sma_50) and close_now > sma_50:
            above_50_count += 1
        if pd.notna(sma_200) and close_now > sma_200:
            above_200_count += 1
        # 52-week high/low detection
        if len(prices) >= 252:
            hi_252 = float(prices["High"].iloc[-252:].max())
            lo_252 = float(prices["Low"].iloc[-252:].min())
            today_high = float(prices["High"].iloc[-1])
            today_low = float(prices["Low"].iloc[-1])
            if today_high >= hi_252: new_highs += 1
            if today_low <= lo_252: new_lows += 1

    pct_above_200 = (above_200_count / total * 100) if total else 0
    pct_above_50 = (above_50_count / total * 100) if total else 0

    # SPY 14-day rate of change
    spy_roc = 0.0
    if len(spy) > BREADTH_ROC_LOOKBACK_DAYS:
        spy_roc = float(
            (spy["Close"].iloc[-1] / spy["Close"].iloc[-(BREADTH_ROC_LOOKBACK_DAYS + 1)] - 1) * 100
        )

    # VIX current level
    vix_level = float(vix["Close"].iloc[-1]) if len(vix) > 0 else 20.0

    sub_scores = {
        "% eligible above 200 SMA": _normalize_pct_above_sma(pct_above_200),
        "% eligible above 50 SMA": _normalize_pct_above_sma(pct_above_50),
        "New 52W highs vs lows": _normalize_high_low_ratio(new_highs, new_lows),
        "SPY 14-day rate of change": _normalize_spy_roc(spy_roc),
        "VIX (inverted)": _normalize_vix(vix_level),
    }

    weekly_score = round(sum(sub_scores.values()) / len(sub_scores), 1)

    # Monthly = rolling 4-week average of stored weekly scores
    breadth_history = history.setdefault("_breadth", [])
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    # Replace today's entry if scan re-ran; else append
    breadth_history = [b for b in breadth_history if b["date"] != today_str]
    breadth_history.append({"date": today_str, "score": weekly_score})
    # Keep last 20 (~4 weeks of trading days)
    breadth_history = sorted(breadth_history, key=lambda b: b["date"])[-20:]
    history["_breadth"] = breadth_history
    monthly_score = round(sum(b["score"] for b in breadth_history) / len(breadth_history), 1)

    return {
        "weekly_score": weekly_score,
        "monthly_score": monthly_score,
        "subindicators": [
            {"label": label, "value": value} for label, value in sub_scores.items()
        ],
        "raw": {
            "pct_above_200_sma": round(pct_above_200, 1),
            "pct_above_50_sma": round(pct_above_50, 1),
            "new_52w_highs": new_highs,
            "new_52w_lows": new_lows,
            "spy_14d_roc_pct": round(spy_roc, 2),
            "vix_level": round(vix_level, 2),
            "sample_size": total,
        },
    }


# ============================================================================
# Report history (multi-day streak tracking)
# ============================================================================

def load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_PATH.read_text())
    except Exception:
        return {}


def save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


def days_on_report(history: dict, ticker: str) -> int:
    entries = history.get(ticker, [])
    if not entries:
        return 1
    # Count today's appearance + how many trailing consecutive trading days
    # the stock also appeared. Loose definition: count unique dates in trailing window.
    cutoff = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d")
    recent = [d for d in entries if d >= cutoff]
    return len(set(recent)) + 1  # +1 for today


def update_history(history: dict, todays_tickers: list[str]) -> None:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cutoff = (datetime.utcnow() - timedelta(days=HISTORY_RETENTION_DAYS)).strftime("%Y-%m-%d")

    for ticker in todays_tickers:
        entries = history.setdefault(ticker, [])
        if today not in entries:
            entries.append(today)
        # Prune old
        history[ticker] = [d for d in entries if d >= cutoff]
    # Drop empty tickers
    for ticker in list(history.keys()):
        if ticker.startswith("_"):
            continue  # keep meta entries like _breadth
        if not history[ticker]:
            del history[ticker]


# ============================================================================
# Signals archive (rolling 90-day store for the Recent Quality Breakouts section)
# ============================================================================

def load_signals_archive() -> list[dict]:
    if not SIGNALS_ARCHIVE_PATH.exists():
        return []
    try:
        data = json.loads(SIGNALS_ARCHIVE_PATH.read_text())
        return data.get("signals", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_signals_archive(archive: list[dict]) -> None:
    SIGNALS_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_ARCHIVE_PATH.write_text(json.dumps({"signals": archive}, indent=2))


def _extract_max_volume_mult(sig: dict) -> float:
    """Max volume_multiple across all patterns triggered on this signal."""
    patterns = sig.get("patterns", {})
    if not isinstance(patterns, dict):
        return 0.0
    mults = [
        p.get("volume_multiple", 0)
        for p in patterns.values()
        if isinstance(p, dict) and p.get("triggered")
    ]
    return float(max(mults)) if mults else 0.0


def update_signals_archive(
    archive: list[dict], todays_signals: list[dict], today_str: str
) -> list[dict]:
    """Prune old entries, drop any prior entry for today (re-runs), add today's."""
    cutoff = (
        datetime.utcnow() - timedelta(days=ARCHIVE_RETENTION_DAYS)
    ).strftime("%Y-%m-%d")
    archive = [
        s for s in archive
        if s.get("date", "") >= cutoff and s.get("date") != today_str
    ]
    for sig in todays_signals:
        archive.append({
            "date": today_str,
            "ticker": sig["ticker"],
            "name": sig.get("name", ""),
            "sector": sig.get("sector", "Unknown"),
            "score": sig["score"],
            "pattern_labels": sig.get("pattern_labels", []),
            "entry": sig["entry"],
            "stop": sig["stop"],
            "tp1": sig["tp1"],
            "tp2": sig["tp2"],
            "piotroski": sig.get("piotroski"),
            "days_on_report": sig.get("days_on_report", 1),
            "volume_multiple": _extract_max_volume_mult(sig),
        })
    return archive


def compute_recent_high_quality(archive: list[dict], n: int = RECENT_TOP_N) -> list[dict]:
    """Composite-ranked top N unique tickers from the archive.

    Ranking prioritises high-conviction, repeated appearances, and volume:
      keep_score = best_score_achieved
                 + recency_bonus (+15 within 7d / +5 within 21d)
                 + appearance_bonus (+2 per appearance, cap 15)
                 + volume_bonus (+5 if max_vol_mult >= 2.0, +10 if >= 3.0)

    Only tickers whose best score ever met HIGH_QUALITY_THRESHOLD are eligible.
    Each returned entry aggregates the ticker's history: best_score with its
    date, total appearances, latest appearance date, max volume multiple,
    and the peak signal's entry/stop/TP levels.
    """
    if not archive:
        return []

    today = datetime.utcnow().date()

    # Aggregate per ticker
    by_ticker: dict[str, dict] = {}
    for s in archive:
        t = s.get("ticker")
        if not t:
            continue
        score = float(s.get("score", 0))
        vol_mult = float(s.get("volume_multiple", 0))
        date_str = s.get("date", "")

        if t not in by_ticker:
            by_ticker[t] = {
                "ticker": t,
                "name": s.get("name", ""),
                "sector": s.get("sector", "Unknown"),
                "best_score": score,
                "best_score_date": date_str,
                "peak_entry": s.get("entry"),
                "peak_stop": s.get("stop"),
                "peak_tp1": s.get("tp1"),
                "peak_tp2": s.get("tp2"),
                "peak_patterns": s.get("pattern_labels", []),
                "piotroski": s.get("piotroski"),
                "appearances": 1,
                "latest_date": date_str,
                "max_vol_mult": vol_mult,
            }
        else:
            agg = by_ticker[t]
            agg["appearances"] += 1
            if date_str > agg["latest_date"]:
                agg["latest_date"] = date_str
            if vol_mult > agg["max_vol_mult"]:
                agg["max_vol_mult"] = vol_mult
            if score > agg["best_score"]:
                agg["best_score"] = score
                agg["best_score_date"] = date_str
                agg["peak_entry"] = s.get("entry")
                agg["peak_stop"] = s.get("stop")
                agg["peak_tp1"] = s.get("tp1")
                agg["peak_tp2"] = s.get("tp2")
                agg["peak_patterns"] = s.get("pattern_labels", [])
                # Refresh sector/piotroski with the peak signal's values
                if s.get("piotroski") is not None:
                    agg["piotroski"] = s.get("piotroski")

    # Filter: only tickers whose peak score met the quality bar
    eligible = [c for c in by_ticker.values() if c["best_score"] >= HIGH_QUALITY_THRESHOLD]

    # Compute keep_score for ranking
    for c in eligible:
        try:
            latest = datetime.strptime(c["latest_date"], "%Y-%m-%d").date()
            days_since = (today - latest).days
        except (ValueError, TypeError):
            days_since = 999

        # Recency bonus
        if days_since <= 7:
            recency = 15
        elif days_since <= 21:
            recency = 5
        else:
            recency = 0

        # Appearance bonus: 2 per appearance, capped at 15
        appearance_bonus = min(c["appearances"] * 2, 15)

        # Volume bonus
        if c["max_vol_mult"] >= 3.0:
            vol_bonus = 10
        elif c["max_vol_mult"] >= 2.0:
            vol_bonus = 5
        else:
            vol_bonus = 0

        c["keep_score"] = round(c["best_score"] + recency + appearance_bonus + vol_bonus, 1)

    eligible.sort(key=lambda c: c["keep_score"], reverse=True)
    return eligible[:n]


# ============================================================================
# Orchestration
# ============================================================================

def main() -> None:
    log("=== Daily scan starting ===")
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Load inputs
    universe = load_eligible_universe()
    eligible = universe["eligible"]
    log(f"Loaded eligible universe: {len(eligible)} tickers "
        f"(refreshed {universe['refreshed_at']})")

    history = load_history()

    # Fetch SPY and VIX for breadth
    log("Fetching SPY and VIX...")
    spy = fetch_prices(SPY_SYMBOL, period="1y")
    time.sleep(YFINANCE_DELAY_SECONDS)
    vix = fetch_prices(VIX_SYMBOL, period="3mo")
    if spy is None or vix is None:
        sys.exit("ERROR: could not fetch SPY or VIX; aborting scan.")

    # Fetch sector SPDR ETFs and compute sector ranks
    sector_ranks: dict[str, int] = {}
    sector_rs: dict[str, float] = {}
    if SECTOR_GATING_ENABLED:
        log(f"Fetching {len(SECTOR_ETFS)} sector ETFs...")
        sector_etf_data = fetch_sector_etfs()
        sector_rs = compute_sector_rs(sector_etf_data, spy)
        sector_ranks = rank_sectors(sector_rs)
        ranked_display = ", ".join(
            f"{etf}#{r} ({sector_rs.get(etf, 0):+.1f}%)"
            for etf, r in sorted(sector_ranks.items(), key=lambda kv: kv[1])
        )
        log(f"Sector ranks (strongest first): {ranked_display}")

    # ---- Pass 1: pre-confluence filters + pattern detection ----
    log(f"Pass 1 — scanning {len(eligible)} eligible tickers...")
    price_cache: dict[str, pd.DataFrame] = {}
    no_data = 0
    trend_pass = 0
    behavioral_pass = 0
    momentum_pass = 0
    pattern_pass = 0
    raw_candidates: list[dict] = []
    raw_watchlist: list[dict] = []
    raw_supertrend: list[dict] = []
    ticker_rs: dict[str, float] = {}

    for i, entry in enumerate(eligible):
        ticker = entry["ticker"]
        prices = fetch_prices(ticker)
        time.sleep(YFINANCE_DELAY_SECONDS)
        if prices is None:
            no_data += 1
            if (i + 1) % 50 == 0:
                log(f"  {i+1}/{len(eligible)} scanned, {len(raw_candidates)} candidates, {no_data} skipped")
            continue
        price_cache[ticker] = prices

        # Trend filter (Layer 4)
        trend_ok, trend_ctx = passes_trend_filter(prices, spy)
        if not trend_ok:
            if (i + 1) % 50 == 0:
                log(f"  {i+1}/{len(eligible)} scanned, {len(raw_candidates)} candidates")
            continue
        trend_pass += 1

        # Behavioral filter (Layer 5)
        beh_ok, beh_ctx = passes_behavioral_filter(prices, ticker)
        if not beh_ok:
            continue
        behavioral_pass += 1

        # Momentum confluence (NEW — Confluence gate 1)
        mom_ok, mom_ctx = passes_momentum_confluence(prices)
        if not mom_ok:
            continue
        momentum_pass += 1

        # Compute RS vs SPY (will be percentile-ranked after loop); do this
        # BEFORE pattern branching so breakouts, watchlist, AND supertrend
        # all share the same percentile ranking pool.
        rs_val = compute_ticker_rs(prices, spy)
        if rs_val is not None:
            ticker_rs[ticker] = rs_val

        # Supertrend check — orthogonal to breakout/watchlist. A ticker in a
        # strong Supertrend-long state is a candidate regardless of whether
        # any breakout pattern also fired. Same ticker CAN appear in multiple
        # sections (that's useful confluence).
        st_state = patterns.supertrend_state(
            prices, SUPERTREND_ATR_PERIOD, SUPERTREND_MULTIPLIER
        )
        if st_state and st_state["direction"] == 1:
            acc_days_st = patterns.accumulation_day_count(prices, ACCUMULATION_LOOKBACK_DAYS)
            raw_supertrend.append({
                "ticker": ticker,
                "entry": entry,
                "trend_ctx": trend_ctx,
                "beh_ctx": beh_ctx,
                "momentum_ctx": mom_ctx,
                "rs_raw": rs_val,
                "st_state": st_state,
                "accumulation_days": acc_days_st,
            })

        # Pattern detection: pattern fired → breakout candidate; else → watchlist
        p_result = patterns.scan_all_patterns(prices)
        pattern_triggered = patterns.any_triggered(p_result)

        if pattern_triggered:
            pattern_pass += 1
            raw_candidates.append({
                "ticker": ticker,
                "entry": entry,
                "trend_ctx": trend_ctx,
                "beh_ctx": beh_ctx,
                "momentum_ctx": mom_ctx,
                "p_result": p_result,
                "rs_raw": rs_val,
            })
        else:
            # Watchlist: no pattern fired, but trend + behavioral + momentum
            # all passed. Record for Pass 2 scoring (RS + sector gates applied).
            acc_days = patterns.accumulation_day_count(prices, ACCUMULATION_LOOKBACK_DAYS)
            range_pos = patterns.range_52w_position(prices)
            setup = compute_watchlist_setup(prices)
            if setup is None:
                # Already extended past 55-day high with no pattern trigger;
                # not a clean watchlist setup, skip.
                if (i + 1) % 50 == 0:
                    log(f"  {i+1}/{len(eligible)} scanned, "
                        f"{len(raw_candidates)} breakouts, {len(raw_watchlist)} watchlist")
                continue
            raw_watchlist.append({
                "ticker": ticker,
                "entry": entry,
                "trend_ctx": trend_ctx,
                "beh_ctx": beh_ctx,
                "momentum_ctx": mom_ctx,
                "rs_raw": rs_val,
                "accumulation_days": acc_days,
                "range_52w_position": range_pos,
                "setup": setup,
            })

        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(eligible)} scanned, "
                f"{len(raw_candidates)} breakouts, {len(raw_watchlist)} watchlist")

    log(f"Pass 1 complete: {no_data} skipped, {trend_pass} trend, "
        f"{behavioral_pass} behavioral, {momentum_pass} momentum, "
        f"{pattern_pass} patterns → {len(raw_candidates)} breakouts, "
        f"{len(raw_watchlist)} watchlist.")

    # ---- Confluence gates: RS percentile + sector regime ----
    rs_percentiles = compute_rs_percentiles(ticker_rs)

    # ---- Pass 2: apply RS + sector gates, finalize scoring ----
    log("Pass 2 — applying confluence gates and finalizing scores...")
    signals: list[dict] = []
    rs_gated = 0
    sector_gated = 0

    for cand in raw_candidates:
        ticker = cand["ticker"]
        entry = cand["entry"]
        prices = price_cache[ticker]
        rs_pct = rs_percentiles.get(ticker)
        sector_label = entry.get("sector", "Unknown")

        # Confluence gate 2: RS percentile
        if rs_pct is None or rs_pct < RS_PERCENTILE_MIN:
            rs_gated += 1
            continue

        # Confluence gate 3: sector regime
        sector_ok, sector_rank = passes_sector_gate(sector_label, sector_ranks)
        if not sector_ok:
            sector_gated += 1
            continue

        # Score with confluence bonuses
        days_in_cons = patterns.days_since_prior_high(prices)
        streak = days_on_report(history, ticker)
        momentum_pass_count = cand["momentum_ctx"].get("pass_count", 0)
        score, score_breakdown = compute_score(
            cand["p_result"], entry.get("piotroski_f_score"), cand["trend_ctx"],
            days_in_cons, streak,
            rs_percentile=rs_pct, sector_rank=sector_rank,
            momentum_pass_count=momentum_pass_count,
        )
        stops = compute_stop_and_targets(prices, cand["p_result"])

        signals.append({
            "ticker": ticker,
            "name": entry["name"],
            "sector": sector_label,
            "sector_rank": sector_rank,
            "score": score,
            "score_breakdown": score_breakdown,
            "patterns": cand["p_result"],
            "pattern_labels": patterns.pattern_labels(cand["p_result"]),
            "trend_context": cand["trend_ctx"],
            "behavioral": cand["beh_ctx"],
            "momentum_context": cand["momentum_ctx"],
            "rs_percentile": rs_pct,
            "rs_raw": cand["rs_raw"],
            "days_in_consolidation": days_in_cons,
            "days_on_report": streak,
            "piotroski": entry.get("piotroski_f_score"),
            **stops,
        })

    log(f"Pass 2 (breakouts) complete: {rs_gated} dropped by RS<{RS_PERCENTILE_MIN}, "
        f"{sector_gated} dropped by sector gate → {len(signals)} final breakout signals.")

    # ---- Pass 2b: apply same RS + sector gates to watchlist ----
    log("Pass 2b — scoring watchlist candidates...")
    watchlist: list[dict] = []
    wl_rs_gated = 0
    wl_sector_gated = 0

    for cand in raw_watchlist:
        ticker = cand["ticker"]
        entry = cand["entry"]
        rs_pct = rs_percentiles.get(ticker)
        sector_label = entry.get("sector", "Unknown")

        if rs_pct is None or rs_pct < RS_PERCENTILE_MIN:
            wl_rs_gated += 1
            continue
        sector_ok, sector_rank = passes_sector_gate(sector_label, sector_ranks)
        if not sector_ok:
            wl_sector_gated += 1
            continue

        mom_passes = cand["momentum_ctx"].get("pass_count", 0)
        wl_score, wl_breakdown = compute_watchlist_score(
            rs_percentile=rs_pct,
            momentum_passes=mom_passes,
            sector_rank=sector_rank,
            accumulation_days=cand["accumulation_days"],
            range_52w_position=cand["range_52w_position"],
        )

        watchlist.append({
            "ticker": ticker,
            "name": entry["name"],
            "sector": sector_label,
            "sector_rank": sector_rank,
            "watchlist_score": wl_score,
            "watchlist_breakdown": wl_breakdown,
            "rs_percentile": rs_pct,
            "momentum_passes": mom_passes,
            "accumulation_days": cand["accumulation_days"],
            "range_52w_position": cand["range_52w_position"],
            "piotroski": entry.get("piotroski_f_score"),
            **cand["setup"],  # current, trigger, stop_pending, tp1_pending, tp2_pending, pct_to_trigger
        })

    log(f"Pass 2b (watchlist) complete: {wl_rs_gated} dropped by RS, "
        f"{wl_sector_gated} dropped by sector → {len(watchlist)} watchlist entries.")

    # ---- Pass 2c: Supertrend longs — same RS + sector gates ----
    log("Pass 2c — scoring Supertrend-long candidates...")
    supertrend_list: list[dict] = []
    st_rs_gated = 0
    st_sector_gated = 0

    for cand in raw_supertrend:
        ticker = cand["ticker"]
        entry = cand["entry"]
        rs_pct = rs_percentiles.get(ticker)
        sector_label = entry.get("sector", "Unknown")

        if rs_pct is None or rs_pct < RS_PERCENTILE_MIN:
            st_rs_gated += 1
            continue
        sector_ok, sector_rank = passes_sector_gate(sector_label, sector_ranks)
        if not sector_ok:
            st_sector_gated += 1
            continue

        mom_passes = cand["momentum_ctx"].get("pass_count", 0)
        st_score, st_breakdown = compute_supertrend_score(
            st_state=cand["st_state"],
            rs_percentile=rs_pct,
            momentum_passes=mom_passes,
            sector_rank=sector_rank,
            accumulation_days=cand["accumulation_days"],
        )

        supertrend_list.append({
            "ticker": ticker,
            "name": entry["name"],
            "sector": sector_label,
            "sector_rank": sector_rank,
            "supertrend_score": st_score,
            "supertrend_breakdown": st_breakdown,
            "rs_percentile": rs_pct,
            "momentum_passes": mom_passes,
            "accumulation_days": cand["accumulation_days"],
            "piotroski": entry.get("piotroski_f_score"),
            "close": cand["st_state"]["close"],
            "supertrend_level": cand["st_state"]["level"],
            "stop_distance_pct": cand["st_state"]["stop_distance_pct"],
            "days_since_flip": cand["st_state"]["days_since_flip"],
        })

    log(f"Pass 2c (supertrend) complete: {st_rs_gated} dropped by RS, "
        f"{st_sector_gated} dropped by sector → {len(supertrend_list)} supertrend longs.")

    # Update history with today's signals (breakouts, watchlist, supertrend) BEFORE breadth
    update_history(history, [s["ticker"] for s in signals])
    update_history(history, [w["ticker"] for w in watchlist])
    update_history(history, [s["ticker"] for s in supertrend_list])

    # Compute market breadth
    log("Computing market breadth...")
    breadth = compute_market_breadth(price_cache, spy, vix, history)

    # Persist history (now includes breadth entry)
    save_history(history)

    # Market regime adjustment: raise minimum shown score when breadth is Adverse
    adaptive_min_score = SCORING["min_show_score"]
    if breadth["weekly_score"] < BREADTH_ADVERSE_THRESHOLD:
        adaptive_min_score = SCORING["min_show_score_adverse"]
        log(f"Market regime: Adverse (weekly breadth {breadth['weekly_score']:.1f}). "
            f"Raising min show score {SCORING['min_show_score']} -> {adaptive_min_score}.")

    # ---- Elite display filter: curate "today" sections to a small set ----
    # Archives retain everything above base gates; only displayed set is strict.

    def is_elite_breakout(s: dict) -> bool:
        rs_pct = s.get("rs_percentile") or 0
        mom_passes = s.get("momentum_context", {}).get("pass_count", 0)
        sector_rank = s.get("sector_rank") or 99
        return (
            s["score"] >= adaptive_min_score
            and rs_pct >= ELITE_RS_PERCENTILE_MIN
            and mom_passes >= ELITE_MOMENTUM_PASSES_MIN
            and sector_rank <= ELITE_SECTOR_RANK_MAX
        )

    def is_elite_watchlist(w: dict) -> bool:
        rs_pct = w.get("rs_percentile") or 0
        mom_passes = w.get("momentum_passes", 0)
        sector_rank = w.get("sector_rank") or 99
        acc_days = w.get("accumulation_days", 0)
        return (
            w["watchlist_score"] >= WATCHLIST_MIN_SHOW_SCORE
            and rs_pct >= ELITE_RS_PERCENTILE_MIN
            and mom_passes >= ELITE_MOMENTUM_PASSES_MIN
            and sector_rank <= ELITE_SECTOR_RANK_MAX
            and acc_days >= ELITE_WATCHLIST_MIN_ACC_DAYS
        )

    elite_breakouts = [s for s in signals if is_elite_breakout(s)]
    elite_breakouts.sort(key=lambda s: s["score"], reverse=True)
    shown = elite_breakouts[:MAX_BREAKOUTS_SHOWN]

    elite_watchlist = [w for w in watchlist if is_elite_watchlist(w)]
    elite_watchlist.sort(key=lambda w: w["watchlist_score"], reverse=True)
    watchlist_shown = elite_watchlist[:MAX_WATCHLIST_SHOWN]

    def is_elite_supertrend(s: dict) -> bool:
        rs_pct = s.get("rs_percentile") or 0
        mom_passes = s.get("momentum_passes", 0)
        sector_rank = s.get("sector_rank") or 99
        return (
            s["supertrend_score"] >= SUPERTREND_MIN_SHOW_SCORE
            and rs_pct >= ELITE_RS_PERCENTILE_MIN
            and mom_passes >= ELITE_MOMENTUM_PASSES_MIN
            and sector_rank <= ELITE_SECTOR_RANK_MAX
        )

    elite_supertrend = [s for s in supertrend_list if is_elite_supertrend(s)]
    elite_supertrend.sort(key=lambda s: s["supertrend_score"], reverse=True)
    supertrend_shown = elite_supertrend[:MAX_SUPERTREND_SHOWN]

    log(f"Elite filter: {len(elite_breakouts)} breakouts qualified → top {len(shown)} shown; "
        f"{len(elite_watchlist)} watchlist qualified → top {len(watchlist_shown)} shown; "
        f"{len(elite_supertrend)} supertrend qualified → top {len(supertrend_shown)} shown.")

    # Sector breakdown across all signals (not just shown)
    sector_counts: dict = {}
    for s in signals:
        sector_counts[s["sector"]] = sector_counts.get(s["sector"], 0) + 1

    funnel = {
        "eligible": len(eligible),
        "no_data": no_data,
        "trend_pass": trend_pass,
        "behavioral_pass": behavioral_pass,
        "momentum_pass": momentum_pass,
        "pattern_pass": pattern_pass,
        "rs_gated": rs_gated,
        "sector_gated": sector_gated,
        "signals": len(signals),
        "elite_breakouts": len(elite_breakouts),
        "shown": len(shown),
        "watchlist_raw": len(raw_watchlist),
        "watchlist_signals": len(watchlist),
        "elite_watchlist": len(elite_watchlist),
        "watchlist_shown": len(watchlist_shown),
        "supertrend_raw": len(raw_supertrend),
        "supertrend_signals": len(supertrend_list),
        "elite_supertrend": len(elite_supertrend),
        "supertrend_shown": len(supertrend_shown),
        "max_breakouts_cap": MAX_BREAKOUTS_SHOWN,
        "max_watchlist_cap": MAX_WATCHLIST_SHOWN,
        "max_supertrend_cap": MAX_SUPERTREND_SHOWN,
        "min_show_score_used": adaptive_min_score,
    }

    # Render report
    log(f"Rendering report ({len(shown)} breakouts, {len(watchlist_shown)} watchlist shown)...")

    # Update rolling BREAKOUT archive and compute Recent Quality Breakouts
    log("Updating signals archive...")
    archive = load_signals_archive()
    archive = update_signals_archive(archive, signals, today_str)
    save_signals_archive(archive)
    recent_quality = compute_recent_high_quality(archive, n=RECENT_TOP_N)
    log(f"Breakout archive: {len(archive)} signals in last {ARCHIVE_RETENTION_DAYS} days; "
        f"{len(recent_quality)} recent-quality tickers (score ≥ {HIGH_QUALITY_THRESHOLD}).")

    # Update rolling WATCHLIST archive and compute Recent Quality Watchlist
    log("Updating watchlist archive...")
    wl_archive = load_watchlist_archive()
    wl_archive = update_watchlist_archive(wl_archive, watchlist, today_str)
    save_watchlist_archive(wl_archive)
    recent_quality_watchlist = compute_recent_quality_watchlist(wl_archive, n=WATCHLIST_RECENT_TOP_N)
    log(f"Watchlist archive: {len(wl_archive)} entries in last {ARCHIVE_RETENTION_DAYS} days; "
        f"{len(recent_quality_watchlist)} recent-quality watchlist tickers "
        f"(score ≥ {WATCHLIST_QUALITY_THRESHOLD}).")

    # Update rolling SUPERTREND archive and compute Recent Quality Supertrend
    log("Updating supertrend archive...")
    st_archive = load_supertrend_archive()
    st_archive = update_supertrend_archive(st_archive, supertrend_list, today_str)
    save_supertrend_archive(st_archive)
    recent_quality_supertrend = compute_recent_quality_supertrend(st_archive, n=SUPERTREND_RECENT_TOP_N)
    log(f"Supertrend archive: {len(st_archive)} entries in last {ARCHIVE_RETENTION_DAYS} days; "
        f"{len(recent_quality_supertrend)} recent-quality supertrend tickers "
        f"(score ≥ {SUPERTREND_QUALITY_THRESHOLD}).")

    html = report.render(
        date_str=today_str,
        generated_at_utc=generated_at,
        breadth=breadth,
        candidates=shown,
        watchlist=watchlist_shown,
        supertrend=supertrend_shown,
        recent_quality=recent_quality,
        recent_quality_watchlist=recent_quality_watchlist,
        recent_quality_supertrend=recent_quality_supertrend,
        sector_counts=sector_counts,
        funnel=funnel,
        eligible_refreshed_at=universe["refreshed_at"][:10],
    )
    report_path = report.write_report(html, REPORTS_DIR, today_str)
    log(f"Wrote {report_path}")

    # Regenerate root index.html so GitHub Pages has a landing page
    log("Updating index.html for site landing...")
    latest_meta = {
        "date": today_str,
        "weekly_breadth": breadth["weekly_score"],
        "monthly_breadth": breadth["monthly_score"],
        "signals": len(signals),
        "shown": len(shown),
        "top_ticker": shown[0]["ticker"] if shown else None,
        "top_score": shown[0]["score"] if shown else None,
        "eligible": len(eligible),
    }
    index_html = report.render_index(REPORTS_DIR, latest_meta)
    index_path = report.write_index(index_html)
    log(f"=== Done. Wrote {report_path} and {index_path} ===")


if __name__ == "__main__":
    main()
