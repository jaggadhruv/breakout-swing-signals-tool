# Breakout Swing Trading Tool

Standalone US-market breakout scanner. Discovery-focused: surfaces swing trade
candidates from your curated universe of ~300–600 fundamentally-solid stocks.

Two parts, one input, one output:

```
build_universe.py  (quarterly, manual, <1 min)
  Your CSV export from a stock screener → eligible_universe.json

daily_scan.py  (Mon-Fri after US close, ~5 min via GitHub Actions)
  eligible_universe.json → trend + behavioral filters → breakout detection
  → scoring → stops/targets → market breadth → reports/YYYY-MM-DD.html
```

Reports live in `reports/`. Multi-day streak state lives in `data/report_history.json`.
Both are committed by CI so history is visible in the repo.

Zero paid services. Zero secrets. All data from yfinance (free, no key needed).

---

## Quarterly workflow — build your eligible universe

Every ~3 months, refresh your stock list from a free screener. **Full step-by-step: [SCREENING.md](SCREENING.md).**

Quick reference:

1. Screen on **Stockanalysis.com** (free CSV export) or Finviz (better filters, manual copy for free tier)
2. Apply the filter recipe (see SCREENING.md — country, market cap, price, volume, sector, EPS, revenue growth, D/E, ROE)
3. Save the export as `input/manual_universe.csv` (overwrite the previous quarter's file)
4. Commit and push — the next daily scan auto-rebuilds `eligible_universe.json` and runs

Expected result: 300–600 stocks. Takes 5 min end-to-end.

---

## Setup (one-time)

### Local

```bash
git clone <your-fork-url>
cd breakout-swing-tool
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### GitHub Actions

Push to your GitHub repo. Under the **Actions** tab, enable workflows if prompted.

Grant workflow write permission so the daily scan can commit reports back:
**Settings → Actions → General → Workflow permissions → Read and write permissions**.

That's it. **No secrets needed.** The tool doesn't hit any authenticated APIs.

The **Daily Scan** workflow runs Mon–Fri at 22:00 UTC. It won't run until
`eligible_universe.json` exists in the repo (build it locally first).

### First run

```bash
# 1. Screen and export from your chosen tool (see SCREENING.md for the recipe)
# 2. Save the CSV as input/manual_universe.csv (already-provided sample works too)

# 3. (Optional local test) Build and scan locally to verify:
python build_universe.py
python daily_scan.py
open reports/*.html

# 4. Commit and push
git add input/ eligible_universe.json reports/ data/
git commit -m "Initial universe and first scan"
git push
```

From here, GitHub Actions runs the daily scan every weekday at 22:00 UTC.
It auto-rebuilds `eligible_universe.json` from your CSV, runs the scan,
and commits everything back. You just review `reports/YYYY-MM-DD.html`
on weekends.

---

## What each layer does

**Universe (Script 1: build_universe.py)**

Reads your manual CSV export and normalises it. All fundamental screening
happens in your screener before you export — the tool trusts your picks.

**Daily scan (Script 2: daily_scan.py)**

| Layer | Filter | Notes |
|-------|--------|-------|
| 4     | Above 50 & 200 SMA; 200 SMA rising; within 25% of 52-week high | Recomputed daily via yfinance |
| 5     | No -10% gap-down in last 20 sessions; earnings-check disabled by default | Toggle `ENABLE_EARNINGS_CHECK` in `daily_scan.py` |
| Detect | 20 / 55 / 252-week high; horizontal resistance break; VCP break | All require volume ≥ 1.5x 20-day avg |
| Score  | See scoring rubric below | 0–100+, only score ≥ 40 shown in report |
| Stops  | Stop = tighter of (breakout × 0.93) or 20-day swing low; TP1 = 2R; TP2 = 3R | Caps risk at ~7% while respecting a tight base |

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
| Piotroski bonus                 | piotroski × 2, capped at 18 (not applied in manual mode — Piotroski isn't computed) |
| Trend context bonus             | +10 if 200 SMA rising AND within 15% of 52W high |
| Multi-day streak bonus          | +5 per consecutive day on report, capped at 15  |

**Multi-day streak** is where the hybrid cadence (daily runs, weekend review) earns
its keep. A stock that appears 3 days in a row is a materially stronger signal than
a one-day flash — genuine breakouts tend to hold, false starts don't.

Without the Piotroski bonus, max realistic score is ~130 instead of ~145. Adjust
`min_show_score` in `daily_scan.py` if you want to see more/fewer candidates.

---

## Market breadth (0–10, weekly + monthly)

Five sub-indicators, each normalised to 0–10, then averaged:

| Sub-indicator                     | Normalisation                          |
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
| Piotroski   | 0–9 fundamental quality (— in manual mode)                              |
| Streak      | Days appearing on the report (×N means N consecutive)                   |
| Sector      | From your CSV                                                           |

Below the table:
- Sector distribution across all breakout signals today
- Funnel: eligible → trend-pass → behavioral-pass → signals → shown

---

## Configuration knobs

All thresholds are top-of-file constants in `daily_scan.py`:

- Trend filter: `TREND_*`
- Behavioral filter: `BEHAVIORAL_*`, `ENABLE_EARNINGS_CHECK`
- Scoring weights: `SCORING` dict
- Stops/targets: `STOP_*`, `TP*_R_MULTIPLE`
- Breadth normalisation: `_normalize_*` functions

---

## Deliberate v1 limitations

- **US only.**
- **No cup-and-handle or flag/pennant detection.** Automated detection false-positive rate is too high without visual review.
- **No Piotroski score in manual mode.** The screener you use before export can filter on similar quality metrics; the scoring bonus is just skipped.
- **Earnings check off by default.** Toggle `ENABLE_EARNINGS_CHECK = True` if you want it — yfinance earnings dates are unreliable and roughly double scan runtime.
- **No intraday.** End-of-day close data only.

---

## Not investment advice

For personal research. All signals require your own judgment. Backtest before
sizing up. The scoring rubric is opinionated and unbacktested — treat the
score as a heuristic ranking, not a probability.
