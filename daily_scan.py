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
RECOVERY_ARCHIVE_PATH = Path("data/recovery_archive.json")
SETUPS_ARCHIVE_PATH = Path("data/setups_archive.json")          # S/R, retest, reversal, RSI, positional
FUNDAMENTALS_CACHE_PATH = Path("data/fundamentals_cache.json")
REPORTS_DIR = Path("reports")

YFINANCE_DELAY_SECONDS = 0.3
PRICE_HISTORY_PERIOD = "3y"   # 3y so monthly RSI(14) has enough bars

# Recent-quality section: rolling 1-week archive of past signals (same rollover
# cadence as the Positional Trading Tool — each run drops entries > 7 days old).
ARCHIVE_RETENTION_DAYS = 7
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
# base gates, so Recent Quality sections keep building a rolling 7-day history.
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
SUPERTREND_MAX_FLIP_AGE_DAYS = 20   # hide stale flips — only recent (fresh signal) ones

# ----------------------------------------------------------------------------
# Recovery (20 EMA crossing above 200 EMA from below) — "coming out of correction"
# ----------------------------------------------------------------------------
# Looser gates than elite because recovery stocks by definition had recent
# weakness, so RS is still rebuilding. Still gated on momentum improving + sector.
RECOVERY_SHORT_EMA_PERIOD    = 20   # 20 EMA
RECOVERY_LONG_EMA_PERIOD     = 200  # 200 EMA
RECOVERY_MAX_DISTANCE_PCT    = 10.0 # 20 EMA max 10% above 200 EMA (else too extended)
RECOVERY_CROSSOVER_LOOKBACK  = 30   # crossover must have happened within last 30 bars
RECOVERY_RISING_LOOKBACK     = 5    # 20 EMA must be rising vs 5 bars ago
RECOVERY_RS_MIN              = 60   # looser than base RS gate (75) and elite (85)
RECOVERY_SECTOR_RANK_MAX     = 7    # looser than elite (4)
RECOVERY_MOMENTUM_PASSES_MIN = 3    # at least 3/4 momentum checks
RECOVERY_MIN_SHOW_SCORE      = 55   # modest display bar given looser gates
RECOVERY_QUALITY_THRESHOLD   = 65   # bar for history inclusion
RECOVERY_RECENT_TOP_N        = 10
MAX_RECOVERY_SHOWN           = 6

# ----------------------------------------------------------------------------
# Shared "quality base" for S/R, break-retest and reversal sections (Pass 1c):
# behavioral filter + close above a rising 200 SMA. These setups are often in
# pullbacks, so they skip the main trend/momentum gates and use their own.
# ----------------------------------------------------------------------------
SR_LOOKBACK_BARS        = 120   # ~6 months of pivots
SR_PIVOT_WING           = 5     # bars each side to confirm a swing high/low
SR_CLUSTER_PCT          = 1.5   # pivots within 1.5% merge into one level
SR_MIN_TOUCHES          = 2     # a level needs ≥ 2 touches
SR_NEAR_PCT             = 3.0   # "near" = within 3% of the level
SR_SUPPORT_RS_MIN       = 60    # pullbacks to support have softer RS
SR_RESISTANCE_RS_MIN    = 70
SR_SECTOR_RANK_MAX      = 6
SR_MIN_SHOW_SCORE       = 60
MAX_SUPPORT_SHOWN       = 10
MAX_RESISTANCE_SHOWN    = 10

RETEST_MAX_AGE_BARS     = 20    # breakout must be 1-20 sessions old
RETEST_LEVEL_WINDOW     = 55    # breakout = close above prior 55-session high
RETEST_BAND_PCT         = 2.0   # pullback low within 2% above the level = retest
RETEST_FAIL_PCT         = 3.0   # close > 3% below level = failed, excluded
RETEST_RS_MIN           = 70
RETEST_SECTOR_RANK_MAX  = 6
RETEST_MIN_SHOW_SCORE   = 60
MAX_RETEST_SHOWN        = 8
MAX_HOLDING_SHOWN       = 8

REVERSAL_MIN_PULLBACK_PCT = 5.0
REVERSAL_MAX_PULLBACK_PCT = 25.0
REVERSAL_RSI_OVERSOLD     = 40.0
REVERSAL_RS_MIN           = 55   # pullbacks dent RS; long-term trend is the real filter
REVERSAL_SECTOR_RANK_MAX  = 7
REVERSAL_MIN_SHOW_SCORE   = 55
MAX_REVERSAL_SHOWN        = 6

# Fake-breakout handling and high-probability retests
FAKE_RS_MIN               = 60   # only show fakeouts in names you'd otherwise care about
MAX_FAKE_SHOWN            = 8
HP_MIN_RESISTANCE_TOUCHES = 2    # breakout level must be an old resistance tested ≥ 2×
HP_SCORE_BONUS            = 15
FAKE_FLAG_PENALTY         = 5    # per fake-breakout flag on retest / holding rows

# ----------------------------------------------------------------------------
# Liquidity filter — applied to EVERY section (before any pipeline runs).
# Thin names give unreliable breakouts, wide spreads and slippage.
# ----------------------------------------------------------------------------
MIN_PRICE                 = 10.0
MIN_AVG_VOLUME            = 500_000      # 20-session average shares/day
MIN_AVG_DOLLAR_VOLUME     = 10_000_000   # 20-session average close × volume

# ----------------------------------------------------------------------------
# Multi-timeframe RSI momentum bounce
# ----------------------------------------------------------------------------
MTF_RSI_MONTHLY_MIN       = 60
MTF_RSI_WEEKLY_MIN        = 60
MTF_RSI_DAILY_LEVEL       = 50
MTF_RSI_CROSS_LOOKBACK    = 3     # daily cross above 50 within last 3 sessions
MTF_RSI_MIN_CROSS_VOL     = 1.0   # volume on the cross day ≥ 1.0× 20-day average
MTF_RSI_RS_MIN            = 60
MTF_RSI_SECTOR_RANK_MAX   = 7
MTF_RSI_MIN_SHOW_SCORE    = 60
MAX_MTF_RSI_SHOWN         = 8

# Liquidity tiers shown on every suggestion (20-session average dollar volume)
LIQUIDITY_TIERS = [(100_000_000, "Very high"), (25_000_000, "High"), (MIN_AVG_DOLLAR_VOLUME, "Adequate")]

# 7-day quality lists for the setup types that previously had no history.
# Threshold = best score a ticker must reach this week to appear in the list.
SETUP_QUALITY_THRESHOLDS = {
    "resistance": 70, "support": 70, "retest": 70, "holding": 70,
    "reversal": 65, "mtf_rsi": 70, "positional": 75,
}

# ----------------------------------------------------------------------------
# Positional: financially strong companies at a fair valuation, not overextended
# ----------------------------------------------------------------------------
FUNDAMENTALS_MAX_AGE_DAYS        = 7     # refresh weekly
FUNDAMENTALS_ERROR_RETRY_DAYS    = 3     # retry failed lookups after 3 days
FUNDAMENTALS_MAX_REFRESH_PER_RUN = 120   # keeps the daily run inside the CI timeout
FUNDAMENTALS_DELAY_SECONDS       = 0.5
POS_MIN_ROE                      = 0.10  # 10%
POS_MAX_DEBT_TO_EQUITY           = 200   # Yahoo reports D/E in percent (200 = 2.0×)
POS_MAX_PEG                      = 2.0
POS_MAX_FORWARD_PE_NO_PEG        = 30    # fallback when PEG is unavailable
POS_MAX_PCT_ABOVE_200SMA         = 15.0  # not overextended vs long-term trend
POS_MAX_PCT_ABOVE_50SMA          = 8.0   # not stretched vs medium-term trend
POS_MAX_DAILY_RSI                = 65
POS_MAX_WEEKLY_RSI               = 70
POS_RS_MIN                       = 40    # trend matters less for positional; avoid clear laggards
POS_SECTOR_RANK_MAX              = 11    # no sector gate (valuation-led)
POS_MIN_SHOW_SCORE               = 70
MAX_POSITIONAL_SHOWN             = 8

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



def sector_rank_ok(rank: int | None, max_rank: int) -> bool:
    """Sector check for elite / recovery filters. A missing rank (sector not in
    the CSV, or not mappable to a SPDR ETF) is NOT gated, consistent with
    passes_sector_gate. Without this, a CSV lacking a Sector column makes every
    elite filter fail and the "today" sections are permanently empty."""
    return rank is None or rank <= max_rank

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
# Recovery — 20 EMA crossing above 200 EMA from below, within distance window
# ============================================================================

def compute_recovery_score(
    *,
    recovery_state: dict,
    rs_percentile: float | None,
    momentum_passes: int,
    sector_rank: int | None,
    accumulation_days: int,
) -> tuple[float, dict]:
    """Composite recovery quality score (0 to ~142).

    Freshness and closeness to the 200 EMA weigh heavily — the whole point of
    this section is "stock just recovered, not yet extended".
    """
    breakdown: dict = {}
    total = 0.0

    days_since = recovery_state.get("days_since_cross", 999)
    if days_since <= 5:
        freshness = 30
    elif days_since <= 10:
        freshness = 25
    elif days_since <= 20:
        freshness = 15
    elif days_since <= 30:
        freshness = 5
    else:
        freshness = 0
    breakdown["freshness"] = freshness
    total += freshness

    dist = recovery_state.get("distance_pct", 999)
    if dist <= 3:
        closeness = 20
    elif dist <= 5:
        closeness = 15
    elif dist <= 7:
        closeness = 10
    elif dist <= 10:
        closeness = 5
    else:
        closeness = 0
    breakdown["closeness"] = closeness
    total += closeness

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


def load_recovery_archive() -> list[dict]:
    if not RECOVERY_ARCHIVE_PATH.exists():
        return []
    try:
        data = json.loads(RECOVERY_ARCHIVE_PATH.read_text())
        return data.get("recovery", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save_recovery_archive(archive: list[dict]) -> None:
    RECOVERY_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECOVERY_ARCHIVE_PATH.write_text(json.dumps({"recovery": archive}, indent=2))


def update_recovery_archive(
    archive: list[dict], todays_entries: list[dict], today_str: str
) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=ARCHIVE_RETENTION_DAYS)).strftime("%Y-%m-%d")
    archive = [s for s in archive if s.get("date", "") >= cutoff and s.get("date") != today_str]
    for e in todays_entries:
        archive.append({
            "date": today_str,
            "ticker": e["ticker"],
            "name": e.get("name", ""),
            "sector": e.get("sector", "Unknown"),
            "sector_rank": e.get("sector_rank"),
            "recovery_score": e["recovery_score"],
            "rs_percentile": e.get("rs_percentile"),
            "momentum_passes": e.get("momentum_passes", 0),
            "accumulation_days": e.get("accumulation_days", 0),
            "close": e.get("close"),
            "short_ema": e.get("short_ema"),
            "long_ema": e.get("long_ema"),
            "distance_pct": e.get("distance_pct"),
            "days_since_cross": e.get("days_since_cross"),
            "piotroski": e.get("piotroski"),
        })
    return archive


def compute_recent_quality_recovery(archive: list[dict], n: int = RECOVERY_RECENT_TOP_N) -> list[dict]:
    """Composite-ranked top N unique recovery tickers from the 7-day archive."""
    if not archive:
        return []

    today = datetime.utcnow().date()
    by_ticker: dict[str, dict] = {}
    for s in archive:
        t = s.get("ticker")
        if not t:
            continue
        score = float(s.get("recovery_score", 0))
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
                "peak_short_ema": s.get("short_ema"),
                "peak_long_ema": s.get("long_ema"),
                "peak_distance_pct": s.get("distance_pct"),
                "peak_days_since_cross": s.get("days_since_cross"),
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
                agg["peak_short_ema"] = s.get("short_ema")
                agg["peak_long_ema"] = s.get("long_ema")
                agg["peak_distance_pct"] = s.get("distance_pct")
                agg["peak_days_since_cross"] = s.get("days_since_cross")
                agg["peak_rs_percentile"] = s.get("rs_percentile")
                agg["peak_momentum_passes"] = s.get("momentum_passes", 0)
                agg["peak_accumulation_days"] = s.get("accumulation_days", 0)
                if s.get("piotroski") is not None:
                    agg["piotroski"] = s.get("piotroski")

    eligible = [c for c in by_ticker.values() if c["best_score"] >= RECOVERY_QUALITY_THRESHOLD]

    for c in eligible:
        try:
            latest = datetime.strptime(c["latest_date"], "%Y-%m-%d").date()
            days_since = (today - latest).days
        except (ValueError, TypeError):
            days_since = 999
        recency = 15 if days_since <= 7 else (5 if days_since <= 21 else 0)
        appearance_bonus = min(c["appearances"] * 2, 15)
        acc_bonus = min(c["peak_accumulation_days"], 10)
        c["keep_score"] = round(c["best_score"] + recency + appearance_bonus + acc_bonus, 1)

    eligible.sort(key=lambda c: c["keep_score"], reverse=True)
    return eligible[:n]



# ============================================================================
# Support / resistance, break-and-retest, reversal — scoring helpers
# ============================================================================

def _sector_points(rank: int | None) -> float:
    if rank is None or rank > 7:
        return 0
    return min((8 - rank) * 2, 12)


def _closeness_points(distance_pct: float) -> float:
    if distance_pct <= 1.0:
        return 20
    if distance_pct <= 2.0:
        return 15
    if distance_pct <= SR_NEAR_PCT:
        return 10
    return 0


def passes_liquidity(prices: pd.DataFrame) -> tuple[bool, dict]:
    """Minimum price, share volume and dollar volume (20-session averages)."""
    if len(prices) < 21:
        return False, {}
    close = float(prices["Close"].iloc[-1])
    avg_vol = float(prices["Volume"].iloc[-20:].mean())
    avg_dollar = float((prices["Close"].iloc[-20:] * prices["Volume"].iloc[-20:]).mean())
    ok = close >= MIN_PRICE and avg_vol >= MIN_AVG_VOLUME and avg_dollar >= MIN_AVG_DOLLAR_VOLUME
    return ok, {"close": close, "avg_vol": avg_vol, "avg_dollar_vol": avg_dollar}


def liquidity_profile(ctx: dict) -> dict:
    """Display-ready liquidity levels for a ticker (from passes_liquidity ctx)."""
    dollar = ctx.get("avg_dollar_vol", 0.0)
    tier = next((name for floor, name in LIQUIDITY_TIERS if dollar >= floor), "Below minimum")
    return {
        "tier": tier,
        "avg_vol": ctx.get("avg_vol", 0.0),
        "avg_dollar_vol": dollar,
        "one_pct_adv": dollar * 0.01,   # position-size ceiling to avoid moving the price
    }


# ---------------- Fundamentals (positional section) ----------------

def load_fundamentals_cache() -> dict:
    if not FUNDAMENTALS_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(FUNDAMENTALS_CACHE_PATH.read_text())
    except Exception:
        return {}


def save_fundamentals_cache(cache: dict) -> None:
    FUNDAMENTALS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FUNDAMENTALS_CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))


def fetch_fundamentals(ticker: str) -> dict | None:
    """Valuation and quality fields from Yahoo's info endpoint. None on failure."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return None
    if len(info) < 10:
        return None
    def num(key):
        v = info.get(key)
        return float(v) if isinstance(v, (int, float)) and v == v else None  # drop NaN
    peg = num("pegRatio") or num("trailingPegRatio")
    return {
        "trailing_pe": num("trailingPE"), "forward_pe": num("forwardPE"), "peg": peg,
        "roe": num("returnOnEquity"), "profit_margin": num("profitMargins"),
        "revenue_growth": num("revenueGrowth"), "earnings_growth": num("earningsGrowth"),
        "debt_to_equity": num("debtToEquity"), "free_cashflow": num("freeCashflow"),
        "market_cap": num("marketCap"),
    }


def refresh_fundamentals(cache: dict, tickers: list[str], today_str: str) -> tuple[int, int]:
    """Refresh missing/stale cache entries (capped per run). Returns (refreshed, failed)."""
    today = datetime.strptime(today_str, "%Y-%m-%d").date()
    def stale(t):
        e = cache.get(t)
        if not e:
            return True
        try:
            age = (today - datetime.strptime(e["fetched"], "%Y-%m-%d").date()).days
        except (KeyError, ValueError):
            return True
        return age >= (FUNDAMENTALS_ERROR_RETRY_DAYS if e.get("error") else FUNDAMENTALS_MAX_AGE_DAYS)
    todo = sorted((t for t in tickers if stale(t)), key=lambda t: (t in cache, cache.get(t, {}).get("fetched", "")))
    refreshed = failed = 0
    for t in todo[:FUNDAMENTALS_MAX_REFRESH_PER_RUN]:
        f = fetch_fundamentals(t)
        time.sleep(FUNDAMENTALS_DELAY_SECONDS)
        if f is None:
            cache[t] = {"fetched": today_str, "error": True}
            failed += 1
        else:
            cache[t] = {**f, "fetched": today_str}
            refreshed += 1
    return refreshed, failed


def evaluate_positional(f: dict, tech: dict) -> dict | None:
    """Quality + valuation + extension. Returns scored components or None if it
    fails a hard gate (unprofitable, over-levered, expensive, overextended)."""
    roe, margin, fcf = f.get("roe"), f.get("profit_margin"), f.get("free_cashflow")
    de, growth = f.get("debt_to_equity"), f.get("revenue_growth")
    fpe, tpe, peg, mcap = f.get("forward_pe"), f.get("trailing_pe"), f.get("peg"), f.get("market_cap")

    # Hard gates: financially sound
    if roe is None or margin is None or roe < POS_MIN_ROE or margin <= 0:
        return None
    if fcf is not None and fcf <= 0:
        return None
    if de is not None and de > POS_MAX_DEBT_TO_EQUITY:
        return None
    # Hard gates: fair valuation
    if fpe is None or fpe <= 0:
        return None
    if peg is not None and peg > 0:
        if peg > POS_MAX_PEG:
            return None
        valuation_label = "Undervalued" if peg <= 1.0 else "Fair"
    else:
        peg = None
        if fpe > POS_MAX_FORWARD_PE_NO_PEG:
            return None
        valuation_label = "Undervalued" if fpe <= 15 else "Fair"
    # Hard gates: not overextended
    if not (0 <= tech["pct_above_200"] <= POS_MAX_PCT_ABOVE_200SMA):
        return None
    if tech["pct_above_50"] > POS_MAX_PCT_ABOVE_50SMA:
        return None
    if tech["rsi"] > POS_MAX_DAILY_RSI or (tech["weekly_rsi"] is not None and tech["weekly_rsi"] > POS_MAX_WEEKLY_RSI):
        return None

    quality = (12 if roe >= 0.20 else 8 if roe >= 0.15 else 4)
    quality += (10 if margin >= 0.20 else 6 if margin >= 0.10 else 2)
    if growth is not None:
        quality += (10 if growth >= 0.15 else 6 if growth >= 0.05 else 2 if growth > 0 else 0)
    if de is not None:
        quality += (8 if de <= 50 else 5 if de <= 100 else 2)
    if fcf is not None and fcf > 0:
        quality += 10

    fcf_yield = (fcf / mcap) if (fcf and mcap) else None
    valuation = 0
    if peg is not None:
        valuation += 15 if peg <= 1.0 else 10 if peg <= 1.5 else 5
    else:
        valuation += 10 if fpe <= 15 else 5 if fpe <= 25 else 0
    if fcf_yield is not None:
        valuation += 10 if fcf_yield >= 0.05 else 6 if fcf_yield >= 0.03 else 3 if fcf_yield >= 0.015 else 0
    if tpe and fpe < tpe:
        valuation += 5   # earnings expected to grow

    ext = (10 if tech["pct_above_200"] <= 5 else 6 if tech["pct_above_200"] <= 10 else 3)
    ext += (10 if 40 <= tech["rsi"] <= 55 else 5 if tech["rsi"] <= 65 else 0)
    return {"quality_pts": quality, "valuation_pts": valuation, "extension_pts": ext,
            "valuation_label": valuation_label, "fcf_yield": fcf_yield, "peg_used": peg}


# ---------------- Generic 7-day archive for setup types without their own ----------------

def load_setups_archive() -> list[dict]:
    if not SETUPS_ARCHIVE_PATH.exists():
        return []
    try:
        return json.loads(SETUPS_ARCHIVE_PATH.read_text()).get("entries", [])
    except Exception:
        return []


def save_setups_archive(entries: list[dict]) -> None:
    SETUPS_ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETUPS_ARCHIVE_PATH.write_text(json.dumps({"entries": entries}, indent=1))


def update_setups_archive(entries: list[dict], rows_by_setup: dict[str, list[dict]], today_str: str) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=ARCHIVE_RETENTION_DAYS)).strftime("%Y-%m-%d")
    entries = [e for e in entries if e.get("date", "") >= cutoff and e.get("date") != today_str]
    level_key = {"support": "level", "resistance": "level", "retest": "breakout_level", "holding": "breakout_level",
                 "reversal": "entry", "mtf_rsi": "entry", "positional": "close"}
    for setup, rows in rows_by_setup.items():
        for r in rows:
            entries.append({
                "date": today_str, "setup": setup, "ticker": r["ticker"],
                "sector": r.get("sector", "Unknown"), "sector_rank": r.get("sector_rank"),
                "score": r["score"], "close": r.get("close"), "level": r.get(level_key[setup]),
                "stop": r.get("stop"), "target": r.get("target", r.get("tp1")),
                "high_probability": bool(r.get("high_probability")),
            })
    return entries


def compute_recent_setups(entries: list[dict], setups: list[str], n: int = 10) -> list[dict]:
    """Best day per (setup, ticker) this week, above the setup's quality threshold,
    ranked by best score + recency + repeat appearances."""
    today = datetime.utcnow().date()
    best: dict[tuple, dict] = {}
    for e in entries:
        if e.get("setup") not in setups:
            continue
        key = (e["setup"], e["ticker"])
        agg = best.get(key)
        if agg is None:
            best[key] = {**e, "best_score": e["score"], "best_score_date": e["date"],
                         "latest_date": e["date"], "appearances": 1}
            continue
        agg["appearances"] += 1
        agg["latest_date"] = max(agg["latest_date"], e["date"])
        agg["high_probability"] = agg["high_probability"] or e.get("high_probability", False)
        if e["score"] > agg["best_score"]:
            agg.update({k: e[k] for k in ("close", "level", "stop", "target", "sector_rank")})
            agg["best_score"], agg["best_score_date"] = e["score"], e["date"]
    out = []
    for agg in best.values():
        if agg["best_score"] < SETUP_QUALITY_THRESHOLDS.get(agg["setup"], 70):
            continue
        try:
            days = (today - datetime.strptime(agg["latest_date"], "%Y-%m-%d").date()).days
        except ValueError:
            days = 99
        agg["keep_score"] = round(agg["best_score"] + (15 if days <= 2 else 5 if days <= 5 else 0)
                                  + min(agg["appearances"] * 2, 15), 1)
        out.append(agg)
    return sorted(out, key=lambda a: a["keep_score"], reverse=True)[:n]


def compute_mtf_rsi_score(*, m: dict, rs_percentile: float, sector_rank: int | None,
                          accumulation_days: int) -> float:
    score = min((m["monthly_rsi"] - 60) * 1.5, 15) + min((m["weekly_rsi"] - 60) * 1.5, 15)
    score += {0: 20, 1: 15, 2: 10}.get(m["cross_age"], 5)
    vm = m["cross_vol_mult"]
    score += 15 if vm >= 1.5 else (10 if vm >= 1.2 else 5)
    score += 10 if m["daily_rsi_dip"] <= 40 else (5 if m["daily_rsi_dip"] <= 45 else 0)
    score += rs_percentile / 2 + _sector_points(sector_rank) + min(accumulation_days, 10)
    return round(score, 1)


def volume_dry_up(prices: pd.DataFrame) -> bool:
    """Last 5 sessions' average volume < 80% of the prior 20-session average.
    Quiet volume into a level = sellers (at support) or supply (at resistance)
    drying up — a constructive sign."""
    if len(prices) < 26:
        return False
    recent = float(prices["Volume"].iloc[-5:].mean())
    base = float(prices["Volume"].iloc[-25:-5].mean())
    return base > 0 and recent < 0.8 * base


def compute_support_score(*, sr: dict, rs_percentile: float, sector_rank: int | None,
                          dry_up: bool, sma50: float) -> float:
    s = sr["support"]
    score = _closeness_points(s["distance_pct"]) + min(s["touches"], 5) * 4
    score += rs_percentile / 2 + _sector_points(sector_rank)
    if dry_up:
        score += 10
    if sma50 and abs(s["level"] - sma50) / sma50 * 100 <= 2.0:
        score += 10  # horizontal level + 50 SMA confluence
    return round(score, 1)


def compute_resistance_score(*, sr: dict, rs_percentile: float, sector_rank: int | None,
                             dry_up: bool, momentum_passes: int, accumulation_days: int) -> float:
    r = sr["resistance"]
    score = _closeness_points(r["distance_pct"]) + min(r["touches"], 5) * 4
    score += rs_percentile / 2 + _sector_points(sector_rank)
    score += momentum_passes * 5 + min(accumulation_days, 10)
    if dry_up:
        score += 10  # tightening under resistance (VCP-like)
    return round(score, 1)


def compute_retest_score(*, bo: dict, rs_percentile: float, sector_rank: int | None,
                         momentum_passes: int) -> float:
    score = 25 if bo["status"] == "retest" else 10
    if bo["status"] == "retest" and bo["bounce_today"]:
        score += 10
    score += min(max((bo["breakout_vol_mult"] - 1.5) * 10, 0), 15)
    score += 10 if bo["breakout_age"] <= 5 else (5 if bo["breakout_age"] <= 10 else 0)
    if bo["status"] == "holding" and bo["extension_pct"] > 10:
        score -= 10  # extended — chasing risk
    score += rs_percentile / 2 + momentum_passes * 5 + _sector_points(sector_rank)
    return round(score, 1)


def compute_reversal_score(*, rv: dict, rs_percentile: float, sector_rank: int | None,
                           today_vol_mult: float | None) -> float:
    score = {"Bullish engulfing": 20, "Outside reversal": 20, "Hammer": 15}.get(rv["trigger"], 0)
    pb = rv["pullback_pct"]
    score += 15 if 8 <= pb <= 15 else (8 if 5 <= pb <= 20 else 0)
    if rv["rsi_now"] - rv["rsi_min5"] >= 5:
        score += 10
    if rv["near_sma50"]:
        score += 10
    if today_vol_mult is not None and today_vol_mult >= 1.2:
        score += 10
    score += rs_percentile / 2 + _sector_points(sector_rank)
    return round(score, 1)


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
# Signals archive (rolling 7-day store for the Recent Quality Breakouts section)
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
    mapped = sum(1 for e in eligible if sector_etf_for(e.get("sector", "")))
    if mapped < len(eligible) * 0.5:
        log(f"WARNING: only {mapped}/{len(eligible)} tickers have a mappable sector. "
            f"Sector gates are effectively OFF. Add a Sector column to "
            f"input/manual_universe.csv (see SCREENING.md).")
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
    raw_recovery: list[dict] = []
    ticker_rs: dict[str, float] = {}
    illiquid: set[str] = set()
    liquidity_info: dict[str, dict] = {}

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

        # Liquidity filter — applies to every section (Pass 1b/1c skip these too)
        liq_ok, liq_ctx = passes_liquidity(prices)
        liquidity_info[ticker] = liquidity_profile(liq_ctx)
        if not liq_ok:
            illiquid.add(ticker)
            continue

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
        f"{len(raw_watchlist)} watchlist, {len(raw_supertrend)} supertrend.")

    # ---- Pass 1b: Recovery scan (independent of trend filter) ----
    # Recovery stocks have been WEAK recently (crossed below 200 EMA, now recovering)
    # so they typically fail the main trend filter (close within 25% of 52W high).
    # We run a dedicated pass that only requires behavioral filter + momentum ≥ 3/4.
    log("Pass 1b — scanning for 20/200 EMA recovery setups (coming out of correction)...")
    recovery_scanned = 0
    recovery_behavioral_pass = 0
    recovery_cross_pass = 0
    recovery_momentum_pass = 0
    eligible_lookup = {e["ticker"]: e for e in eligible}

    for ticker, prices in price_cache.items():
        entry_info = eligible_lookup.get(ticker)
        if not entry_info or ticker in illiquid:
            continue
        recovery_scanned += 1

        beh_ok, _ = passes_behavioral_filter(prices, ticker)
        if not beh_ok:
            continue
        recovery_behavioral_pass += 1

        recovery_state = patterns.golden_cross_recovery(
            prices,
            short_period=RECOVERY_SHORT_EMA_PERIOD,
            long_period=RECOVERY_LONG_EMA_PERIOD,
            max_distance_pct=RECOVERY_MAX_DISTANCE_PCT,
            crossover_lookback_days=RECOVERY_CROSSOVER_LOOKBACK,
            rising_lookback_days=RECOVERY_RISING_LOOKBACK,
        )
        if recovery_state is None:
            continue
        recovery_cross_pass += 1

        _, mom_ctx = passes_momentum_confluence(prices)
        if mom_ctx.get("pass_count", 0) < RECOVERY_MOMENTUM_PASSES_MIN:
            continue
        recovery_momentum_pass += 1

        # Compute RS if not already (recovery tickers may not have passed main trend filter)
        rs_val = ticker_rs.get(ticker)
        if rs_val is None:
            rs_val = compute_ticker_rs(prices, spy)
            if rs_val is not None:
                ticker_rs[ticker] = rs_val

        acc_days = patterns.accumulation_day_count(prices, ACCUMULATION_LOOKBACK_DAYS)

        raw_recovery.append({
            "ticker": ticker,
            "entry": entry_info,
            "mom_ctx": mom_ctx,
            "rs_raw": rs_val,
            "recovery_state": recovery_state,
            "accumulation_days": acc_days,
        })

    log(f"Pass 1b complete: {recovery_scanned} scanned → {recovery_behavioral_pass} behavioral → "
        f"{recovery_cross_pass} valid crossovers → {recovery_momentum_pass} momentum-OK "
        f"→ {len(raw_recovery)} recovery candidates.")

    # ---- Pass 1c: full-universe RS + quality-base setups ----
    # (1) Compute raw RS for EVERY fetched ticker so percentiles rank against the
    #     whole universe (previously only trend-filter survivors were ranked,
    #     which made "RS >= 75" mean "top 25% of the strongest 25%").
    # (2) Collect support/resistance, break-retest and reversal candidates from a
    #     "quality base": behavioral filter + close above a rising 200 SMA.
    log("Pass 1c — full-universe RS + support/resistance, break-retest, reversal scan...")
    raw_sr: list[dict] = []
    raw_retest: list[dict] = []
    raw_reversal: list[dict] = []
    raw_mtf_rsi: list[dict] = []
    raw_positional: list[dict] = []
    quality_base_pass = 0

    for ticker, prices in price_cache.items():
        entry_info = eligible_lookup.get(ticker)
        if not entry_info or ticker in illiquid:
            continue
        if ticker not in ticker_rs:
            rs_val = compute_ticker_rs(prices, spy)
            if rs_val is not None:
                ticker_rs[ticker] = rs_val

        if len(prices) < 221:
            continue
        beh_ok, _ = passes_behavioral_filter(prices, ticker)
        if not beh_ok:
            continue

        m_rsi = patterns.mtf_rsi_bounce(
            prices, MTF_RSI_MONTHLY_MIN, MTF_RSI_WEEKLY_MIN, MTF_RSI_DAILY_LEVEL, MTF_RSI_CROSS_LOOKBACK
        )
        if m_rsi and m_rsi["cross_vol_mult"] >= MTF_RSI_MIN_CROSS_VOL:
            raw_mtf_rsi.append({"ticker": ticker, "entry": entry_info, "m": m_rsi,
                                "acc_days": patterns.accumulation_day_count(prices, ACCUMULATION_LOOKBACK_DAYS)})

        close_s = prices["Close"]
        sma200 = close_s.rolling(200).mean()
        if not (close_s.iloc[-1] > sma200.iloc[-1] and sma200.iloc[-1] > sma200.iloc[-21]):
            continue
        quality_base_pass += 1

        # Positional candidate: record extension metrics; fundamentals checked after the loop
        sma50_now = float(close_s.rolling(50).mean().iloc[-1])
        close_now = float(close_s.iloc[-1])
        weekly_close = close_s.resample("W-FRI").last().dropna()
        raw_positional.append({
            "ticker": ticker, "entry": entry_info,
            "close": close_now, "sma50": sma50_now, "sma200": float(sma200.iloc[-1]),
            "high_252": float(prices["High"].iloc[-252:].max()),
            "tech": {
                "pct_above_200": (close_now / float(sma200.iloc[-1]) - 1) * 100,
                "pct_above_50": (close_now / sma50_now - 1) * 100,
                "rsi": float(patterns.rsi(close_s, 14).iloc[-1]),
                "weekly_rsi": float(patterns.rsi(weekly_close, 14).iloc[-1]) if len(weekly_close) >= 30 else None,
            },
        })

        _, mom_ctx_c = passes_momentum_confluence(prices)
        base = {
            "ticker": ticker,
            "entry": entry_info,
            "sma50": float(close_s.rolling(50).mean().iloc[-1]),
            "dry_up": volume_dry_up(prices),
            "mom_passes": mom_ctx_c.get("pass_count", 0),
        }

        sr = patterns.nearest_support_resistance(
            prices, SR_LOOKBACK_BARS, SR_PIVOT_WING, SR_CLUSTER_PCT, SR_MIN_TOUCHES
        )
        near_s = sr["support"] is not None and sr["support"]["distance_pct"] <= SR_NEAR_PCT
        near_r = sr["resistance"] is not None and sr["resistance"]["distance_pct"] <= SR_NEAR_PCT
        if near_s or near_r:
            raw_sr.append({**base, "sr": sr,
                           "acc_days": patterns.accumulation_day_count(prices, ACCUMULATION_LOOKBACK_DAYS)})

        bo = patterns.recent_breakout_status(
            prices, max_age=RETEST_MAX_AGE_BARS, level_window=RETEST_LEVEL_WINDOW,
            vol_mult_min=patterns.VOLUME_MULTIPLE_THRESHOLD,
            retest_band_pct=RETEST_BAND_PCT, fail_pct=RETEST_FAIL_PCT,
        )
        if bo:
            raw_retest.append({**base, "bo": bo})

        rv = patterns.reversal_swing_setup(
            prices, REVERSAL_MIN_PULLBACK_PCT, REVERSAL_MAX_PULLBACK_PCT, REVERSAL_RSI_OVERSOLD
        )
        if rv:
            raw_reversal.append({**base, "rv": rv, "vol_mult": patterns.volume_multiple(prices)})

    log(f"Pass 1c complete: RS computed for {len(ticker_rs)} tickers; {quality_base_pass} in quality base "
        f"→ {len(raw_sr)} near S/R, {len(raw_retest)} recent breakouts, {len(raw_reversal)} reversal triggers, "
        f"{len(raw_mtf_rsi)} MTF-RSI bounces; {len(illiquid)} illiquid tickers excluded.")

    # ---- Fundamentals for positional candidates (cached, weekly refresh, capped) ----
    fundamentals = load_fundamentals_cache()
    f_refreshed, f_failed = refresh_fundamentals(
        fundamentals, [c["ticker"] for c in raw_positional], today_str
    )
    save_fundamentals_cache(fundamentals)
    f_available = sum(1 for c in raw_positional
                      if c["ticker"] in fundamentals and not fundamentals[c["ticker"]].get("error"))
    log(f"Fundamentals: refreshed {f_refreshed}, failed {f_failed}; "
        f"{f_available}/{len(raw_positional)} positional candidates have data.")

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
            "fake_flags": patterns.todays_breakout_risk(prices, stops.get("breakout_level_used")),
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

    # ---- Pass 2d: Recovery — looser RS (60) + sector (top 7) gates ----
    log("Pass 2d — scoring recovery candidates (looser gates than elite)...")
    recovery_list: list[dict] = []
    rec_rs_gated = 0
    rec_sector_gated = 0

    for cand in raw_recovery:
        ticker = cand["ticker"]
        entry = cand["entry"]
        rs_pct = rs_percentiles.get(ticker)
        sector_label = entry.get("sector", "Unknown")

        if rs_pct is None or rs_pct < RECOVERY_RS_MIN:
            rec_rs_gated += 1
            continue

        # Recovery accepts top 7 sectors (vs top 6 for main gates). Ranks are
        # keyed by SPDR ETF, so map the sector label first; unmapped = not gated.
        etf = sector_etf_for(sector_label)
        rank = sector_ranks.get(etf) if etf else None
        if not sector_rank_ok(rank, RECOVERY_SECTOR_RANK_MAX):
            rec_sector_gated += 1
            continue

        mom_passes = cand["mom_ctx"].get("pass_count", 0)
        rec_score, rec_breakdown = compute_recovery_score(
            recovery_state=cand["recovery_state"],
            rs_percentile=rs_pct,
            momentum_passes=mom_passes,
            sector_rank=rank,
            accumulation_days=cand["accumulation_days"],
        )

        recovery_list.append({
            "ticker": ticker,
            "name": entry["name"],
            "sector": sector_label,
            "sector_rank": rank,
            "recovery_score": rec_score,
            "recovery_breakdown": rec_breakdown,
            "rs_percentile": rs_pct,
            "momentum_passes": mom_passes,
            "accumulation_days": cand["accumulation_days"],
            "piotroski": entry.get("piotroski_f_score"),
            "close": cand["recovery_state"]["close"],
            "short_ema": cand["recovery_state"]["short_ema"],
            "long_ema": cand["recovery_state"]["long_ema"],
            "distance_pct": cand["recovery_state"]["distance_pct"],
            "days_since_cross": cand["recovery_state"]["days_since_cross"],
        })

    log(f"Pass 2d (recovery) complete: {rec_rs_gated} dropped by RS<{RECOVERY_RS_MIN}, "
        f"{rec_sector_gated} dropped by sector → {len(recovery_list)} recovery entries.")

    # ---- Pass 2e: S/R, break-retest, reversal — gates + scoring ----
    log("Pass 2e — scoring support/resistance, break-retest, reversal candidates...")

    def _rank_for(entry_d: dict) -> int | None:
        etf = sector_etf_for(entry_d.get("sector", "Unknown"))
        return sector_ranks.get(etf) if etf else None

    def _common(c: dict, rs_pct: float, rank: int | None) -> dict:
        e = c["entry"]
        return {
            "ticker": c["ticker"], "name": e.get("name", ""), "sector": e.get("sector", "Unknown"),
            "sector_rank": rank, "rs_percentile": rs_pct, "momentum_passes": c["mom_passes"],
            "piotroski": e.get("piotroski_f_score"), "dry_up": c["dry_up"],
        }

    support_list: list[dict] = []
    resistance_list: list[dict] = []
    for c in raw_sr:
        rs_pct = rs_percentiles.get(c["ticker"])
        rank = _rank_for(c["entry"])
        if rs_pct is None or not sector_rank_ok(rank, SR_SECTOR_RANK_MAX):
            continue
        sr = c["sr"]
        sup, res = sr["support"], sr["resistance"]
        if sup and sup["distance_pct"] <= SR_NEAR_PCT and rs_pct >= SR_SUPPORT_RS_MIN:
            support_list.append({
                **_common(c, rs_pct, rank),
                "score": compute_support_score(sr=sr, rs_percentile=rs_pct, sector_rank=rank,
                                               dry_up=c["dry_up"], sma50=c["sma50"]),
                "close": sr["close"], "level": sup["level"], "touches": sup["touches"],
                "distance_pct": sup["distance_pct"],
                "stop": round(sup["level"] * 0.97, 2),
                "target": res["level"] if res else None,
                "sma50_confluence": abs(sup["level"] - c["sma50"]) / c["sma50"] * 100 <= 2.0,
            })
        if res and res["distance_pct"] <= SR_NEAR_PCT and rs_pct >= SR_RESISTANCE_RS_MIN:
            resistance_list.append({
                **_common(c, rs_pct, rank),
                "score": compute_resistance_score(sr=sr, rs_percentile=rs_pct, sector_rank=rank,
                                                  dry_up=c["dry_up"], momentum_passes=c["mom_passes"],
                                                  accumulation_days=c["acc_days"]),
                "close": sr["close"], "level": res["level"], "touches": res["touches"],
                "distance_pct": res["distance_pct"], "accumulation_days": c["acc_days"],
                "support_below": sup["level"] if sup else None,
            })

    retest_list: list[dict] = []
    holding_list: list[dict] = []
    fake_list: list[dict] = []
    for c in raw_retest:
        rs_pct = rs_percentiles.get(c["ticker"])
        rank = _rank_for(c["entry"])
        bo = c["bo"]
        if rs_pct is None:
            continue

        # Fake / failed breakouts: shown as an "avoid" list, lighter gates
        if bo["status"] in ("failed", "failing"):
            if rs_pct >= FAKE_RS_MIN:
                fake_list.append({**_common(c, rs_pct, rank), **bo,
                                  "score": 100 - bo["breakout_age"]})  # most recent first
            continue

        if rs_pct < RETEST_RS_MIN or not sector_rank_ok(rank, RETEST_SECTOR_RANK_MAX):
            continue
        score = compute_retest_score(bo=bo, rs_percentile=rs_pct, sector_rank=rank,
                                     momentum_passes=c["mom_passes"])
        score -= FAKE_FLAG_PENALTY * len(bo["fake_flags"])
        row = {**_common(c, rs_pct, rank), **bo}

        # High probability: old resistance (≥ 2 touches) retested as support,
        # bounce today, and zero fake-breakout flags.
        row["high_probability"] = (
            bo["status"] == "retest"
            and bo["bounce_today"]
            and bo["resistance_touches"] >= HP_MIN_RESISTANCE_TOUCHES
            and not bo["fake_flags"]
        )
        if row["high_probability"]:
            score += HP_SCORE_BONUS
        row["score"] = round(score, 1)

        if bo["status"] == "retest":
            row["stop"] = round(min(bo["recent_low"], bo["breakout_level"]) * 0.98, 2)
            risk = bo["close"] - row["stop"]
            row["tp1"] = round(bo["close"] + 2 * risk, 2) if risk > 0 else None
            retest_list.append(row)
        else:
            holding_list.append(row)

    # Cross-mark Near Support rows whose support IS a just-broken old resistance
    hp_levels = {r["ticker"]: r["breakout_level"] for r in retest_list if r["high_probability"]}
    for r in support_list:
        lvl = hp_levels.get(r["ticker"])
        r["high_probability"] = lvl is not None and abs(r["level"] - lvl) / lvl * 100 <= 2.0
        if r["high_probability"]:
            r["score"] = round(r["score"] + HP_SCORE_BONUS, 1)

    mtf_rsi_list: list[dict] = []
    for c in raw_mtf_rsi:
        rs_pct = rs_percentiles.get(c["ticker"])
        rank = _rank_for(c["entry"])
        if rs_pct is None or rs_pct < MTF_RSI_RS_MIN or not sector_rank_ok(rank, MTF_RSI_SECTOR_RANK_MAX):
            continue
        e = c["entry"]
        mtf_rsi_list.append({
            "ticker": c["ticker"], "name": e.get("name", ""), "sector": e.get("sector", "Unknown"),
            "sector_rank": rank, "rs_percentile": rs_pct, "accumulation_days": c["acc_days"],
            "piotroski": e.get("piotroski_f_score"), **c["m"],
            "score": compute_mtf_rsi_score(m=c["m"], rs_percentile=rs_pct, sector_rank=rank,
                                           accumulation_days=c["acc_days"]),
        })

    reversal_list: list[dict] = []
    for c in raw_reversal:
        rs_pct = rs_percentiles.get(c["ticker"])
        rank = _rank_for(c["entry"])
        if rs_pct is None or rs_pct < REVERSAL_RS_MIN or not sector_rank_ok(rank, REVERSAL_SECTOR_RANK_MAX):
            continue
        rv = c["rv"]
        reversal_list.append({
            **_common(c, rs_pct, rank), **rv,
            "today_vol_mult": round(c["vol_mult"], 2) if c["vol_mult"] is not None else None,
            "score": compute_reversal_score(rv=rv, rs_percentile=rs_pct, sector_rank=rank,
                                            today_vol_mult=c["vol_mult"]),
        })

    def _curate(rows: list[dict], min_score: float, cap: int) -> tuple[int, list[dict]]:
        q = sorted((r for r in rows if r["score"] >= min_score), key=lambda r: r["score"], reverse=True)
        return len(q), q[:cap]

    support_qualified, support_shown = _curate(support_list, SR_MIN_SHOW_SCORE, MAX_SUPPORT_SHOWN)
    resistance_qualified, resistance_shown = _curate(resistance_list, SR_MIN_SHOW_SCORE, MAX_RESISTANCE_SHOWN)
    retest_qualified, retest_shown = _curate(retest_list, RETEST_MIN_SHOW_SCORE, MAX_RETEST_SHOWN)
    holding_qualified, holding_shown = _curate(holding_list, RETEST_MIN_SHOW_SCORE, MAX_HOLDING_SHOWN)
    reversal_qualified, reversal_shown = _curate(reversal_list, REVERSAL_MIN_SHOW_SCORE, MAX_REVERSAL_SHOWN)
    fake_qualified, fake_shown = _curate(fake_list, 0, MAX_FAKE_SHOWN)
    mtf_rsi_qualified, mtf_rsi_shown = _curate(mtf_rsi_list, MTF_RSI_MIN_SHOW_SCORE, MAX_MTF_RSI_SHOWN)
    high_prob_shown = [r for r in retest_shown if r["high_probability"]]

    log(f"Pass 2e complete: support {len(support_list)}→{len(support_shown)}, "
        f"resistance {len(resistance_list)}→{len(resistance_shown)}, "
        f"retest {len(retest_list)}→{len(retest_shown)}, holding {len(holding_list)}→{len(holding_shown)}, "
        f"reversal {len(reversal_list)}→{len(reversal_shown)}, fake {len(fake_list)}→{len(fake_shown)}, "
        f"MTF-RSI {len(mtf_rsi_list)}→{len(mtf_rsi_shown)}, high-probability retests {len(high_prob_shown)} "
        f"(gated → shown).")

    # ---- Pass 2f: Positional — quality at a fair price, not overextended ----
    positional_list: list[dict] = []
    pos_no_data = 0
    for c in raw_positional:
        f = fundamentals.get(c["ticker"])
        if not f or f.get("error"):
            pos_no_data += 1
            continue
        rs_pct = rs_percentiles.get(c["ticker"])
        rank = _rank_for(c["entry"])
        if rs_pct is None or rs_pct < POS_RS_MIN or not sector_rank_ok(rank, POS_SECTOR_RANK_MAX):
            continue
        ev = evaluate_positional(f, c["tech"])
        if ev is None:
            continue
        e = c["entry"]
        score = ev["quality_pts"] + ev["valuation_pts"] + ev["extension_pts"] + rs_pct / 5 + _sector_points(rank)
        target = c["high_252"] if c["high_252"] > c["close"] * 1.05 else c["close"] * 1.20
        positional_list.append({
            "ticker": c["ticker"], "name": e.get("name", ""), "sector": e.get("sector", "Unknown"),
            "sector_rank": rank, "rs_percentile": rs_pct, "piotroski": e.get("piotroski_f_score"),
            "score": round(score, 1), **ev, **f,
            "close": round(c["close"], 2), "sma50": round(c["sma50"], 2), "sma200": round(c["sma200"], 2),
            "pct_above_200": round(c["tech"]["pct_above_200"], 1), "pct_above_50": round(c["tech"]["pct_above_50"], 1),
            "rsi": round(c["tech"]["rsi"], 1),
            "weekly_rsi": round(c["tech"]["weekly_rsi"], 1) if c["tech"]["weekly_rsi"] is not None else None,
            "stop": round(c["sma200"] * 0.97, 2), "target": round(target, 2),
        })
    positional_qualified, positional_shown = _curate(positional_list, POS_MIN_SHOW_SCORE, MAX_POSITIONAL_SHOWN)
    log(f"Pass 2f (positional) complete: {len(raw_positional)} candidates, {pos_no_data} without fundamentals "
        f"→ {len(positional_list)} pass quality/valuation/extension → {len(positional_shown)} shown.")

    # Update history with today's signals (all four pipelines) BEFORE breadth
    update_history(history, [s["ticker"] for s in signals])
    update_history(history, [w["ticker"] for w in watchlist])
    update_history(history, [s["ticker"] for s in supertrend_list])
    update_history(history, [r["ticker"] for r in recovery_list])

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
        for s_ in signals:  # breakouts in a weak tape fail more often
            s_["fake_flags"] = s_.get("fake_flags", []) + ["Adverse market regime"]

    # ---- Elite display filter: curate "today" sections to a small set ----
    # Archives retain everything above base gates; only displayed set is strict.

    def is_elite_breakout(s: dict) -> bool:
        rs_pct = s.get("rs_percentile") or 0
        mom_passes = s.get("momentum_context", {}).get("pass_count", 0)
        sector_rank = s.get("sector_rank")
        return (
            s["score"] >= adaptive_min_score
            and rs_pct >= ELITE_RS_PERCENTILE_MIN
            and mom_passes >= ELITE_MOMENTUM_PASSES_MIN
            and sector_rank_ok(sector_rank, ELITE_SECTOR_RANK_MAX)
        )

    def is_elite_watchlist(w: dict) -> bool:
        rs_pct = w.get("rs_percentile") or 0
        mom_passes = w.get("momentum_passes", 0)
        sector_rank = w.get("sector_rank")
        acc_days = w.get("accumulation_days", 0)
        return (
            w["watchlist_score"] >= WATCHLIST_MIN_SHOW_SCORE
            and rs_pct >= ELITE_RS_PERCENTILE_MIN
            and mom_passes >= ELITE_MOMENTUM_PASSES_MIN
            and sector_rank_ok(sector_rank, ELITE_SECTOR_RANK_MAX)
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
        sector_rank = s.get("sector_rank")
        flip_age = s.get("days_since_flip", 999)
        return (
            s["supertrend_score"] >= SUPERTREND_MIN_SHOW_SCORE
            and rs_pct >= ELITE_RS_PERCENTILE_MIN
            and mom_passes >= ELITE_MOMENTUM_PASSES_MIN
            and sector_rank_ok(sector_rank, ELITE_SECTOR_RANK_MAX)
            and flip_age <= SUPERTREND_MAX_FLIP_AGE_DAYS   # fresh flips only
        )

    elite_supertrend = [s for s in supertrend_list if is_elite_supertrend(s)]
    elite_supertrend.sort(key=lambda s: s["supertrend_score"], reverse=True)
    supertrend_shown = elite_supertrend[:MAX_SUPERTREND_SHOWN]

    # Recovery has its OWN display criteria — looser than elite, because
    # recovery stocks have had recent weakness and won't yet have RS≥85 etc.
    qualified_recovery = [r for r in recovery_list if r["recovery_score"] >= RECOVERY_MIN_SHOW_SCORE]
    qualified_recovery.sort(key=lambda r: r["recovery_score"], reverse=True)
    recovery_shown = qualified_recovery[:MAX_RECOVERY_SHOWN]

    log(f"Elite filter: {len(elite_breakouts)} breakouts qualified → top {len(shown)} shown; "
        f"{len(elite_watchlist)} watchlist qualified → top {len(watchlist_shown)} shown; "
        f"{len(elite_supertrend)} supertrend qualified → top {len(supertrend_shown)} shown; "
        f"{len(qualified_recovery)} recovery qualified → top {len(recovery_shown)} shown.")

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
        "recovery_raw": len(raw_recovery),
        "recovery_signals": len(recovery_list),
        "qualified_recovery": len(qualified_recovery),
        "recovery_shown": len(recovery_shown),
        "max_breakouts_cap": MAX_BREAKOUTS_SHOWN,
        "max_watchlist_cap": MAX_WATCHLIST_SHOWN,
        "max_supertrend_cap": MAX_SUPERTREND_SHOWN,
        "max_recovery_cap": MAX_RECOVERY_SHOWN,
        "quality_base_pass": quality_base_pass,
        "sr_raw": len(raw_sr), "retest_raw": len(raw_retest), "reversal_raw": len(raw_reversal),
        "support_signals": len(support_list), "support_qualified": support_qualified, "support_shown": len(support_shown),
        "resistance_signals": len(resistance_list), "resistance_qualified": resistance_qualified, "resistance_shown": len(resistance_shown),
        "retest_signals": len(retest_list), "retest_qualified": retest_qualified, "retest_shown": len(retest_shown),
        "holding_signals": len(holding_list), "holding_qualified": holding_qualified, "holding_shown": len(holding_shown),
        "reversal_signals": len(reversal_list), "reversal_qualified": reversal_qualified, "reversal_shown": len(reversal_shown),
        "max_support_cap": MAX_SUPPORT_SHOWN, "max_resistance_cap": MAX_RESISTANCE_SHOWN,
        "max_retest_cap": MAX_RETEST_SHOWN, "max_holding_cap": MAX_HOLDING_SHOWN,
        "max_reversal_cap": MAX_REVERSAL_SHOWN,
        "illiquid": len(illiquid),
        "min_price": MIN_PRICE, "min_avg_volume": MIN_AVG_VOLUME, "min_avg_dollar_volume": MIN_AVG_DOLLAR_VOLUME,
        "fake_signals": len(fake_list), "fake_shown": len(fake_shown), "max_fake_cap": MAX_FAKE_SHOWN,
        "high_prob_shown": len(high_prob_shown),
        "mtf_rsi_raw": len(raw_mtf_rsi), "mtf_rsi_signals": len(mtf_rsi_list),
        "mtf_rsi_qualified": mtf_rsi_qualified, "mtf_rsi_shown": len(mtf_rsi_shown),
        "max_mtf_rsi_cap": MAX_MTF_RSI_SHOWN,
        "positional_raw": len(raw_positional), "positional_no_data": pos_no_data,
        "positional_signals": len(positional_list), "positional_qualified": positional_qualified,
        "positional_shown": len(positional_shown), "max_positional_cap": MAX_POSITIONAL_SHOWN,
        "supertrend_max_flip_age_days": SUPERTREND_MAX_FLIP_AGE_DAYS,
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

    # Update rolling RECOVERY archive and compute Recent Quality Recovery
    log("Updating recovery archive...")
    rec_archive = load_recovery_archive()
    rec_archive = update_recovery_archive(rec_archive, recovery_list, today_str)
    save_recovery_archive(rec_archive)
    recent_quality_recovery = compute_recent_quality_recovery(rec_archive, n=RECOVERY_RECENT_TOP_N)
    log(f"Recovery archive: {len(rec_archive)} entries in last {ARCHIVE_RETENTION_DAYS} days; "
        f"{len(recent_quality_recovery)} recent-quality recovery tickers "
        f"(score ≥ {RECOVERY_QUALITY_THRESHOLD}).")

    # Rolling 7-day quality lists for setup types without their own archive
    setups_archive = update_setups_archive(load_setups_archive(), {
        "support": support_list, "resistance": resistance_list, "retest": retest_list, "holding": holding_list,
        "reversal": reversal_list, "mtf_rsi": mtf_rsi_list, "positional": positional_list,
    }, today_str)
    save_setups_archive(setups_archive)
    recent_resistance = compute_recent_setups(setups_archive, ["resistance"])
    recent_retest = compute_recent_setups(setups_archive, ["retest", "holding"])
    recent_pullback = compute_recent_setups(setups_archive, ["support", "reversal", "mtf_rsi"])
    recent_positional = compute_recent_setups(setups_archive, ["positional"])

    # Attach today's liquidity levels to every row the report will show
    for rows in (shown, watchlist_shown, supertrend_shown, recovery_shown, support_shown,
                 resistance_shown, retest_shown, holding_shown, reversal_shown, fake_shown,
                 high_prob_shown, mtf_rsi_shown, positional_shown, recent_quality,
                 recent_quality_watchlist, recent_quality_supertrend, recent_quality_recovery,
                 recent_resistance, recent_retest, recent_pullback, recent_positional):
        for r in rows:
            r["liquidity"] = liquidity_info.get(r["ticker"])

    html = report.render(
        date_str=today_str,
        generated_at_utc=generated_at,
        breadth=breadth,
        candidates=shown,
        watchlist=watchlist_shown,
        supertrend=supertrend_shown,
        recovery=recovery_shown,
        support=support_shown,
        resistance=resistance_shown,
        retest=retest_shown,
        holding=holding_shown,
        reversal=reversal_shown,
        fake=fake_shown,
        high_prob=high_prob_shown,
        mtf_rsi=mtf_rsi_shown,
        positional=positional_shown,
        recent_resistance=recent_resistance,
        recent_retest=recent_retest,
        recent_pullback=recent_pullback,
        recent_positional=recent_positional,
        recent_quality=recent_quality,
        recent_quality_watchlist=recent_quality_watchlist,
        recent_quality_supertrend=recent_quality_supertrend,
        recent_quality_recovery=recent_quality_recovery,
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
