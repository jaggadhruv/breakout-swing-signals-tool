# Breakout Swing Trading Tool

Standalone US-market breakout scanner. Discovery-focused: surfaces swing trade
candidates from the Russell 3000 that aren't in a curated watchlist.

Two scripts, one input, one output:

```
refresh_universe.py  (quarterly, ~30-60 min)
  Russell 3000 → liquidity → fundamentals → eligible_universe.json (~500-800 stocks)

daily_scan.py  (Mon-Fri after US close, ~2-3 min)
  eligible_universe.json → trend + behavioral filters → breakout detection
  → scoring → stops/targets → market breadth → reports/YYYY-MM-DD.html
```

Reports live in `reports/`. Multi-day streak state lives in `data/report_history.json`.
Both are committed by CI so history is visible in the repo.

---

## Setup

### 1. First-time local setup

```bash
git clone <your-fork-url>
cd breakout-swing-tool
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. SEC User-Agent

SEC EDGAR requires a User-Agent identifying you with a contact email. Set it as
an env var locally and as a GitHub Actions secret named `SEC_USER_AGENT`.

```bash
export SEC_USER_AGENT="Your Name your.email@example.com"
```

In GitHub: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `SEC_USER_AGENT`
- Value: `Your Name your.email@example.com`

### 3. First run (local)

```bash
# Build the initial eligible universe (30-60 min)
python refresh_universe.py

# Run the first scan
python daily_scan.py
open reports/*.html
```

Commit `eligible_universe.json` after the first refresh — CI needs it in the repo.

### 4. Enable GitHub Actions

Push to GitHub. Two workflows will appear under the **Actions** tab:

- **Refresh Universe (Quarterly)** — runs 15 Feb / May / Aug / Nov at 07:00 UTC.
  Trigger manually first to seed the repo.
- **Daily Scan** — runs Mon-Fri at 22:00 UTC. Won't run until
  `eligible_universe.json` exists.

Enable Actions if prompted. Grant workflow write permission if the commit step fails:
**Settings → Actions → General → Workflow permissions → Read and write permissions**.

---

## What each layer does

**Refresh universe (Script 1)**

| Layer | Filter | Notes |
|-------|--------|-------|
| 1     | Russell 3000 via iShares IWV holdings | Sector exclusions applied: Financials, Real Estate |
| 2     | 20-day ADV ≥ $10M and price ≥ $10 | yfinance sequential, 0.3s delays |
| 3     | Profitable 3 of 4 quarters; TTM revenue growth positive; TTM OCF positive; D/E < 2 | SEC EDGAR company facts; AND gate; any missing metric → excluded |

Output includes a computed Piotroski F-score per stock (0-9) as a quality read.
Not used as a hard cutoff.

**Daily scan (Script 2)**

| Layer | Filter | Notes |
|-------|--------|-------|
| 4     | Above 50 & 200 SMA; 200 SMA rising; within 25% of 52-week high | Recomputed daily |
| 5     | No -10% gap-down in last 20 sessions; earnings-check disabled by default | Toggle `ENABLE_EARNINGS_CHECK` in `daily_scan.py` to enable |
| Detect | 20 / 55 / 252-week high; horizontal resistance break; VCP break | All require volume ≥ 1.5x 20-day avg |
| Score  | See scoring rubric below | 0-100+, only score ≥ 40 shown |
| Stops  | Stop = **tighter** of (breakout × 0.93) or 20-day swing low; TP1 = 2R; TP2 = 3R | Caps risk at ~7% while respecting a tight base |

---

## Setup scoring rubric

| Component                       | Points                                          |
|---------------------------------|-------------------------------------------------|
| N-week-20 high                  | +10                                             |
| N-week-55 high                  | +20 (in addition to 20 if both trigger)         |
| N-week-252 (52-week) high       | +30 (in addition to 20 and 55)                  |
| Horizontal resistance break     | +25                                             |
| Volatility contraction break    | +25                                             |
| Volume bonus                    | (vol_multiple − 1.5) × 10, capped at 15         |
| Base length bonus               | days_in_consolidation / 5, capped at 10         |
| Piotroski bonus                 | piotroski × 2, capped at 18                     |
| Trend context bonus             | +10 if 200 SMA rising AND within 15% of 52W high |
| Multi-day streak bonus          | +5 per consecutive day on report, capped at 15  |

**Multi-day streak** is where the hybrid cadence (daily runs, weekend review) earns
its keep. A stock that appears 3 days in a row is a materially stronger signal than
a one-day flash — genuine breakouts tend to hold, false starts don't.

---

## Market breadth (0–10, weekly + monthly)

Five sub-indicators, each normalized to 0–10, then averaged:

| Sub-indicator                     | Normalization                          |
|-----------------------------------|----------------------------------------|
| % of eligible above 200 SMA       | Linear: 0% → 0, 100% → 10              |
| % of eligible above 50 SMA        | Linear: 0% → 0, 100% → 10              |
| New 52W highs vs lows             | Ratio-based: 5:1 → 10, 1:1 → 5, 1:5 → 0 |
| SPY 14-day rate of change         | Linear: −5% → 0, 0 → 5, +5% → 10       |
| VIX (inverted)                    | VIX 10 → 10, VIX 40 → 0                |

- **Weekly** = today's snapshot.
- **Monthly** = rolling average of the last 20 trading days' weekly scores.
- **Verdict**: Adverse (<4), Neutral (4–7), Favorable (>7). Shown in the header.

---

## Reading the report

Ranked candidate table columns:

| Column      | Meaning                                                                 |
|-------------|-------------------------------------------------------------------------|
| Ticker      | Symbol                                                                  |
| Score       | 0–100+ composite; higher = stronger setup                               |
| Patterns    | Which breakout patterns triggered today                                 |
| Entry       | Current close (your reference entry)                                    |
| Stop        | Suggested initial stop-loss                                             |
| TP1 / TP2   | Take-profit targets at 2R and 3R                                        |
| R:R         | Reward-to-risk multiple of TP1                                          |
| Piotroski   | 0-9 fundamental quality (green ≥ 7, red ≤ 3)                            |
| Streak      | Days appearing on the report (×N means N consecutive)                   |
| Sector      | GICS sector                                                             |

Below the table:
- Sector distribution across all breakout signals today
- Funnel: eligible → trend-pass → behavioral-pass → signals → shown

---

## Configuration knobs

All thresholds are top-of-file constants:

- Fundamentals gate: `refresh_universe.py` (`MIN_*`, `MAX_*`)
- Trend filter: `daily_scan.py` (`TREND_*`)
- Behavioral filter: `daily_scan.py` (`BEHAVIORAL_*`, `EARNINGS_LOOKAHEAD_DAYS`)
- Scoring weights: `daily_scan.py` (`SCORING` dict)
- Stops/targets: `daily_scan.py` (`STOP_*`, `TP*_R_MULTIPLE`)
- Breadth normalization: `daily_scan.py` (`_normalize_*` functions)

---

## Deliberate v1 limitations

- **US only.** India universe isn't loaded; would require a separate quarterly refresh.
- **No cup-and-handle or flag/pennant detection.** False-positive rate on automated
  detection is too high without visual review.
- **Piotroski F-score is a simplified version.** Skips shares-outstanding dilution
  check and uses TTM proxies for asset turnover / margin. Good enough as a display
  metric; not used as a hard cutoff.
- **Earnings check is best-effort.** If yfinance can't return earnings dates for
  a ticker, the stock isn't excluded on that basis.
- **No intraday.** End-of-day close data only.
- **Sequential fetches.** Full daily scan runs ~2-3 min for a 500-800 stock pool.

---

## Not investment advice

For personal research. All signals require your own judgment. Backtest before
sizing up. The scoring rubric is opinionated and unbacktested — treat the
score as a heuristic ranking, not a probability.
