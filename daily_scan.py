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
REPORTS_DIR = Path("reports")

YFINANCE_DELAY_SECONDS = 0.3
PRICE_HISTORY_PERIOD = "1y"

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
    "min_show_score":         40,
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
# Setup scoring
# ============================================================================

def compute_score(
    patterns_result: dict,
    piotroski: int | None,
    trend_ctx: dict,
    days_in_consolidation: int,
    days_on_report: int,
) -> tuple[float, dict]:
    """Composite 0-100+ score. Returns (score, breakdown)."""
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

    # Iterate through eligible pool
    log(f"Scanning {len(eligible)} eligible tickers...")
    price_cache: dict[str, pd.DataFrame] = {}
    no_data = 0
    trend_pass = 0
    behavioral_pass = 0
    signals: list[dict] = []

    for i, entry in enumerate(eligible):
        ticker = entry["ticker"]
        prices = fetch_prices(ticker)
        time.sleep(YFINANCE_DELAY_SECONDS)
        if prices is None:
            no_data += 1
            if (i + 1) % 50 == 0:
                log(f"  {i+1}/{len(eligible)} scanned, {len(signals)} signals, {no_data} skipped")
            continue
        price_cache[ticker] = prices

        # Layer 4: trend context
        trend_ok, trend_ctx = passes_trend_filter(prices, spy)
        if not trend_ok:
            if (i + 1) % 50 == 0:
                log(f"  {i+1}/{len(eligible)} scanned, {len(signals)} signals")
            continue
        trend_pass += 1

        # Layer 5: behavioral
        beh_ok, beh_ctx = passes_behavioral_filter(prices, ticker)
        if not beh_ok:
            if (i + 1) % 50 == 0:
                log(f"  {i+1}/{len(eligible)} scanned, {len(signals)} signals")
            continue
        behavioral_pass += 1

        # Pattern detection
        p_result = patterns.scan_all_patterns(prices)
        if not patterns.any_triggered(p_result):
            if (i + 1) % 50 == 0:
                log(f"  {i+1}/{len(eligible)} scanned, {len(signals)} signals")
            continue

        # Compute score inputs
        days_in_cons = patterns.days_since_prior_high(prices)
        streak = days_on_report(history, ticker)
        score, score_breakdown = compute_score(
            p_result, entry.get("piotroski_f_score"), trend_ctx, days_in_cons, streak
        )
        stops = compute_stop_and_targets(prices, p_result)

        signals.append({
            "ticker": ticker,
            "name": entry["name"],
            "sector": entry["sector"],
            "score": score,
            "score_breakdown": score_breakdown,
            "patterns": p_result,
            "pattern_labels": patterns.pattern_labels(p_result),
            "trend_context": trend_ctx,
            "behavioral": beh_ctx,
            "days_in_consolidation": days_in_cons,
            "days_on_report": streak,
            "piotroski": entry.get("piotroski_f_score"),
            **stops,
        })

        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{len(eligible)} scanned, {len(signals)} signals")

    log(f"Scan complete: {no_data} skipped (no yfinance data), "
        f"{trend_pass} passed trend, "
        f"{behavioral_pass} passed behavioral, {len(signals)} signals.")

    # Update history with today's signals BEFORE breadth (breadth stores _breadth entry)
    update_history(history, [s["ticker"] for s in signals])

    # Compute market breadth
    log("Computing market breadth...")
    breadth = compute_market_breadth(price_cache, spy, vix, history)

    # Persist history (now includes breadth entry)
    save_history(history)

    # Filter and rank signals for display
    shown = [s for s in signals if s["score"] >= SCORING["min_show_score"]]
    shown.sort(key=lambda s: s["score"], reverse=True)

    # Sector breakdown across all signals (not just shown)
    sector_counts: dict = {}
    for s in signals:
        sector_counts[s["sector"]] = sector_counts.get(s["sector"], 0) + 1

    funnel = {
        "eligible": len(eligible),
        "no_data": no_data,
        "trend_pass": trend_pass,
        "behavioral_pass": behavioral_pass,
        "signals": len(signals),
        "shown": len(shown),
    }

    # Render report
    log(f"Rendering report ({len(shown)} candidates shown)...")
    html = report.render(
        date_str=today_str,
        generated_at_utc=generated_at,
        breadth=breadth,
        candidates=shown,
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
