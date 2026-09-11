"""
refresh_universe.py

Quarterly universe refresh for the breakout swing trading tool.

Builds the eligible pool of US stocks from the Russell 3000 by applying:
  Layer 1: Universe     -> iShares IWV holdings CSV
  Layer 2: Liquidity    -> 20-day ADV >= $10M and price >= $10
  Layer 3: Fundamentals -> profitable 3/4 quarters, TTM revenue growth,
                           positive TTM operating cash flow, D/E < 2
                           Excludes Financials & Real Estate.
                           Excludes tickers with missing metrics.

Output: eligible_universe.json  (the ~500-800 stock pool for daily_scan.py)

Runtime: ~30-60 minutes (sequential fetches respect API rate limits).
Cadence: mid-Feb, mid-May, mid-Aug, mid-Nov (after peak earnings weeks).

Before first run:
  1. Set SEC_USER_AGENT env var. SEC requires User-Agent with contact info.
     Example:  export SEC_USER_AGENT="Kavya Verma kavya@example.com"
  2. pip install pandas requests yfinance
  3. Verify the iShares IWV holdings URL still works. iShares occasionally
     changes the download endpoint. If the download fails, browse to
     https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/
     and right-click the "Download Holdings" button to grab the fresh URL.

Design decisions (locked in project notes):
  - Standalone tool, does not touch the Supertrend screener
  - US market only
  - AND gate on fundamentals: any single failure excludes the ticker
  - Piotroski F-score shown for context, not used as a hard cutoff
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf


# ============================================================================
# Configuration
# ============================================================================

IWV_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/"
    "1467271812596.ajax?fileType=csv&fileName=IWV_holdings&dataType=fund"
)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# SEC requires a real User-Agent identifying you and your contact email.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "").strip()

# Rate limit spacing
YFINANCE_DELAY_SECONDS = 0.3   # matches the Supertrend tool pattern
SEC_DELAY_SECONDS = 0.15       # SEC caps at 10 req/sec; stay well under

# Liquidity thresholds
MIN_AVG_DAILY_DOLLAR_VOLUME = 10_000_000
MIN_PRICE = 10.00
LIQUIDITY_LOOKBACK_DAYS = 20

# Fundamental gate
MIN_PROFITABLE_QUARTERS_OF_4 = 3
REQUIRE_TTM_REVENUE_GROWTH = True
REQUIRE_POSITIVE_TTM_OCF = True
MAX_DEBT_TO_EQUITY = 2.0

# Sector exclusions (iShares uses GICS labels: "Financials", "Real Estate")
EXCLUDED_SECTORS = {"Financials", "Real Estate"}

OUTPUT_PATH = Path("eligible_universe.json")

# XBRL revenue concept fallbacks. Companies report under different tags.
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]


# ============================================================================
# Utilities
# ============================================================================

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sec_headers() -> dict:
    if not SEC_USER_AGENT:
        sys.exit(
            "ERROR: SEC_USER_AGENT env var not set. SEC requires a User-Agent "
            "identifying you and your contact email. Example:\n"
            '  export SEC_USER_AGENT="Kavya Verma kavya@example.com"'
        )
    return {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}


# ============================================================================
# Layer 1: Universe (Russell 3000 via iShares IWV)
# ============================================================================

def download_iwv_holdings() -> pd.DataFrame:
    """Download current IWV holdings. Returns DataFrame [Ticker, Name, Sector]."""
    print(f"[{now()}] Downloading IWV holdings...")
    r = requests.get(IWV_HOLDINGS_URL, timeout=60)
    r.raise_for_status()

    # iShares CSVs have a header block above the actual data.
    # Find the row that begins with "Ticker,"
    text = r.content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.startswith("Ticker,")), None)
    if start is None:
        raise RuntimeError(
            "Could not find 'Ticker,' header row in IWV CSV. "
            "iShares may have changed the format. Inspect the download."
        )
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))

    # Keep only equity rows (drop cash, futures, forwards, etc.)
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].str.contains("Equity", na=False, case=False)]

    df = df[["Ticker", "Name", "Sector"]].copy()
    # Normalise ticker to yfinance / SEC hyphen convention (BRK.B -> BRK-B)
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.replace(".", "-", regex=False)
    # Keep only valid US common-stock ticker shapes
    df = df[df["Ticker"].str.match(r"^[A-Z\-]+$", na=False)]
    df = df.drop_duplicates(subset="Ticker").reset_index(drop=True)

    print(f"[{now()}] IWV holdings: {len(df)} tickers.")
    return df


# ============================================================================
# Layer 2: Liquidity
# ============================================================================

def check_liquidity(ticker: str) -> dict | None:
    """Fetch recent OHLCV, check ADV and price. Returns stats dict or None."""
    try:
        hist = yf.Ticker(ticker).history(
            period=f"{LIQUIDITY_LOOKBACK_DAYS + 10}d",
            auto_adjust=False,
        )
    except Exception:
        return None

    if hist is None or hist.empty or len(hist) < LIQUIDITY_LOOKBACK_DAYS:
        return None

    recent = hist.tail(LIQUIDITY_LOOKBACK_DAYS)
    avg_dollar_vol = float((recent["Close"] * recent["Volume"]).mean())
    last_price = float(recent["Close"].iloc[-1])

    if avg_dollar_vol < MIN_AVG_DAILY_DOLLAR_VOLUME or last_price < MIN_PRICE:
        return None

    return {
        "avg_daily_dollar_volume": round(avg_dollar_vol, 0),
        "last_price": round(last_price, 2),
    }


# ============================================================================
# Layer 3: Fundamentals (SEC EDGAR company facts)
# ============================================================================

def get_ticker_to_cik() -> dict[str, int]:
    """Fetch SEC's ticker -> CIK mapping."""
    print(f"[{now()}] Fetching SEC ticker -> CIK mapping...")
    r = requests.get(SEC_TICKERS_URL, headers=sec_headers(), timeout=30)
    r.raise_for_status()
    mapping = {}
    for entry in r.json().values():
        ticker = str(entry["ticker"]).upper().replace(".", "-")
        mapping[ticker] = int(entry["cik_str"])
    print(f"[{now()}] Ticker -> CIK mapping loaded: {len(mapping)} tickers.")
    return mapping


def fetch_company_facts(cik: int) -> dict | None:
    """Fetch full XBRL company facts for one CIK. None if 404 or error."""
    url = SEC_COMPANY_FACTS_URL.format(cik=cik)
    try:
        r = requests.get(url, headers=sec_headers(), timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _extract_quarterly_series(
    facts: dict, concepts: list[str], unit: str = "USD"
) -> list[dict] | None:
    """Return quarterly (Q1-Q4) values for the first matching concept.

    Dedupes by end date (keeps latest filed version).
    Returned list is sorted by end date, newest first.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in concepts:
        node = us_gaap.get(concept)
        if not node:
            continue
        units = node.get("units", {}).get(unit)
        if not units:
            continue
        rows = []
        seen_ends = set()
        # Sort by 'filed' desc so we take the latest amendment first
        for row in sorted(units, key=lambda r: r.get("filed", ""), reverse=True):
            end = row.get("end")
            if not end or end in seen_ends:
                continue
            if row.get("fp") not in ("Q1", "Q2", "Q3", "Q4"):
                continue  # skip FY (annual) and unassigned
            seen_ends.add(end)
            rows.append({"end": end, "val": row["val"], "fp": row["fp"]})
        rows.sort(key=lambda r: r["end"], reverse=True)
        if rows:
            return rows
    return None


def _get_latest_instant(facts: dict, concept: str, unit: str = "USD") -> float | None:
    """Most recent instant (balance sheet) value for the concept."""
    node = facts.get("facts", {}).get("us-gaap", {}).get(concept)
    if not node:
        return None
    units = node.get("units", {}).get(unit)
    if not units:
        return None
    instants = [r for r in units if "start" not in r and r.get("end")]
    if not instants:
        return None
    instants.sort(key=lambda r: r["end"], reverse=True)
    return float(instants[0]["val"])


def evaluate_fundamentals(facts: dict) -> dict | None:
    """Apply the AND gate. Returns snapshot dict if pass, None otherwise."""
    # --- Profitability: last 4 quarters, need >= 3 positive ---------------
    ni = _extract_quarterly_series(facts, ["NetIncomeLoss"])
    if not ni or len(ni) < 4:
        return None
    last4 = ni[:4]
    profitable_qtrs = sum(1 for r in last4 if r["val"] > 0)
    if profitable_qtrs < MIN_PROFITABLE_QUARTERS_OF_4:
        return None

    # --- Revenue growth: TTM_now > TTM_prev -------------------------------
    rev = _extract_quarterly_series(facts, REVENUE_CONCEPTS)
    if not rev or len(rev) < 8:
        return None
    ttm_now = sum(r["val"] for r in rev[:4])
    ttm_prev = sum(r["val"] for r in rev[4:8])
    if REQUIRE_TTM_REVENUE_GROWTH and ttm_now <= ttm_prev:
        return None

    # --- Operating cash flow: TTM > 0 -------------------------------------
    ocf = _extract_quarterly_series(facts, ["NetCashProvidedByUsedInOperatingActivities"])
    if not ocf or len(ocf) < 4:
        return None
    ttm_ocf = sum(r["val"] for r in ocf[:4])
    if REQUIRE_POSITIVE_TTM_OCF and ttm_ocf <= 0:
        return None

    # --- Leverage: D/E < 2 -------------------------------------------------
    equity = _get_latest_instant(facts, "StockholdersEquity")
    long_debt = _get_latest_instant(facts, "LongTermDebt") or 0
    short_debt = _get_latest_instant(facts, "ShortTermBorrowings") or 0
    total_debt = long_debt + short_debt
    if not equity or equity <= 0:
        return None
    de = total_debt / equity
    if de >= MAX_DEBT_TO_EQUITY:
        return None

    return {
        "profitable_quarters_of_4": profitable_qtrs,
        "ttm_revenue": round(ttm_now, 0),
        "ttm_revenue_growth_pct": round((ttm_now / ttm_prev - 1) * 100, 2),
        "ttm_ocf": round(ttm_ocf, 0),
        "debt_to_equity": round(de, 3),
    }


def compute_piotroski_f_score(facts: dict) -> int | None:
    """Simplified Piotroski F-score (0-9). Returns None if data insufficient.

    Simplifications from the original Piotroski (1998):
      - Uses TTM values instead of prior-year fiscal for cleaner XBRL parsing
      - Skips shares-outstanding dilution check (item 7)
      - Asset turnover uses revenue growth as a proxy
    Good enough as a display metric; not used as a hard cutoff.
    """
    try:
        ni = _extract_quarterly_series(facts, ["NetIncomeLoss"]) or []
        ocf = _extract_quarterly_series(facts, ["NetCashProvidedByUsedInOperatingActivities"]) or []
        rev = _extract_quarterly_series(facts, REVENUE_CONCEPTS) or []
        assets = _get_latest_instant(facts, "Assets")

        if len(ni) < 8 or len(ocf) < 8 or len(rev) < 8 or not assets or assets <= 0:
            return None

        ttm_ni_now = sum(r["val"] for r in ni[:4])
        ttm_ni_prev = sum(r["val"] for r in ni[4:8])
        ttm_ocf_now = sum(r["val"] for r in ocf[:4])
        ttm_rev_now = sum(r["val"] for r in rev[:4])
        ttm_rev_prev = sum(r["val"] for r in rev[4:8])

        equity = _get_latest_instant(facts, "StockholdersEquity") or 0
        total_debt = (
            (_get_latest_instant(facts, "LongTermDebt") or 0)
            + (_get_latest_instant(facts, "ShortTermBorrowings") or 0)
        )
        curr_assets = _get_latest_instant(facts, "AssetsCurrent")
        curr_liab = _get_latest_instant(facts, "LiabilitiesCurrent")

        score = 0
        # Profitability (4 points)
        if ttm_ni_now > 0:                score += 1  # positive NI
        if ttm_ocf_now > 0:               score += 1  # positive OCF
        if ttm_ni_now > ttm_ni_prev:      score += 1  # improving ROA proxy
        if ttm_ocf_now > ttm_ni_now:      score += 1  # accrual quality
        # Leverage / liquidity (2 points, skipping dilution)
        if equity > 0 and (total_debt / equity) < 1.0:
            score += 1
        if curr_assets and curr_liab and curr_liab > 0 and (curr_assets / curr_liab) > 1.0:
            score += 1
        # Efficiency (2 points; margin proxied by revenue growth, turnover by same)
        if ttm_rev_now > ttm_rev_prev:          score += 1
        if ttm_rev_now > ttm_rev_prev * 1.05:   score += 1

        return score
    except Exception:
        return None


# ============================================================================
# Orchestration
# ============================================================================

def main() -> None:
    print(f"[{now()}] === Quarterly universe refresh starting ===")
    # Fail fast if SEC creds not set
    sec_headers()

    # ---- Layer 1: Universe ------------------------------------------------
    universe = download_iwv_holdings()

    before = len(universe)
    universe = universe[~universe["Sector"].isin(EXCLUDED_SECTORS)].reset_index(drop=True)
    print(f"[{now()}] Sector exclusions dropped {before - len(universe)} tickers. "
          f"Remaining: {len(universe)}.")

    # ---- Layer 2: Liquidity -----------------------------------------------
    print(f"[{now()}] Applying liquidity filter (slow phase, ~15 min)...")
    liquidity_pass = []
    for i, row in universe.iterrows():
        ticker = row["Ticker"]
        stats = check_liquidity(ticker)
        if stats:
            liquidity_pass.append({
                "ticker": ticker,
                "name": row["Name"],
                "sector": row["Sector"],
                **stats,
            })
        if (i + 1) % 100 == 0:
            print(f"  [{now()}]   {i+1}/{len(universe)} checked, "
                  f"{len(liquidity_pass)} pass so far")
        time.sleep(YFINANCE_DELAY_SECONDS)
    print(f"[{now()}] Liquidity filter complete: {len(liquidity_pass)} tickers.")

    # ---- Layer 3: Fundamentals --------------------------------------------
    cik_map = get_ticker_to_cik()

    print(f"[{now()}] Applying fundamental gate (slow phase, ~15 min)...")
    eligible = []
    stats_missing_cik = 0
    stats_missing_facts = 0
    stats_failed_gate = 0

    for i, row in enumerate(liquidity_pass):
        ticker = row["ticker"]
        cik = cik_map.get(ticker)
        if not cik:
            stats_missing_cik += 1
            continue

        facts = fetch_company_facts(cik)
        time.sleep(SEC_DELAY_SECONDS)
        if not facts:
            stats_missing_facts += 1
            continue

        fund = evaluate_fundamentals(facts)
        if fund is None:
            stats_failed_gate += 1
            continue

        piotroski = compute_piotroski_f_score(facts)
        eligible.append({
            **row,
            "cik": cik,
            **fund,
            "piotroski_f_score": piotroski,
        })

        if (i + 1) % 100 == 0:
            print(f"  [{now()}]   {i+1}/{len(liquidity_pass)} checked, "
                  f"{len(eligible)} pass so far")

    print(f"[{now()}] Fundamental gate complete: {len(eligible)} tickers.")
    print(f"  Dropped: {stats_missing_cik} no CIK, "
          f"{stats_missing_facts} no facts, "
          f"{stats_failed_gate} failed gate.")

    # ---- Output -----------------------------------------------------------
    output = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(universe),
        "liquidity_pass": len(liquidity_pass),
        "eligible_count": len(eligible),
        "config_snapshot": {
            "min_avg_daily_dollar_volume": MIN_AVG_DAILY_DOLLAR_VOLUME,
            "min_price": MIN_PRICE,
            "min_profitable_quarters_of_4": MIN_PROFITABLE_QUARTERS_OF_4,
            "require_ttm_revenue_growth": REQUIRE_TTM_REVENUE_GROWTH,
            "require_positive_ttm_ocf": REQUIRE_POSITIVE_TTM_OCF,
            "max_debt_to_equity": MAX_DEBT_TO_EQUITY,
            "excluded_sectors": sorted(EXCLUDED_SECTORS),
        },
        "eligible": eligible,
    }

    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    print(f"[{now()}] === Done. Wrote {OUTPUT_PATH} — {len(eligible)} eligible ===")


if __name__ == "__main__":
    main()
