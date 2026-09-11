# Quarterly Screening Process

The one repeatable procedure for refreshing your eligible universe. Run this
every ~3 months (mid-February, mid-May, mid-August, mid-November — right after
peak earnings weeks).

Total time: ~5–10 minutes.

---

## 1. Open the screener

**Primary: Stockanalysis.com**
https://stockanalysis.com/stocks/screener/

- Truly free
- Direct CSV download button
- Filter set covers everything below

**Alternative: Finviz**
https://finviz.com/screener.ashx?v=111

- Better filter set (60+ filters)
- Free web view, but CSV export is Elite-only ($25/mo)
- If you use it: right-click the results table → Copy → paste into Google Sheets → download as CSV

---

## 2. Apply these filters

Mirror this exactly (or as close as your screener allows). These map to the
locked design decisions in the tool.

| # | Filter                     | Setting                       | Purpose                                                        |
|---|----------------------------|-------------------------------|----------------------------------------------------------------|
| 1 | Country                    | USA                           | Tool is US-only                                                |
| 2 | Exchange                   | NYSE + NASDAQ                 | Skip OTC/pink sheets                                           |
| 3 | Market cap                 | Over $300M                    | Floor ≈ Russell 3000, leaves discovery room below your $2B Supertrend pool |
| 4 | Price                      | Over $10                      | Excludes cheap, wide-spread names                              |
| 5 | Average volume (3 mo)      | Over 500K shares/day          | Proxy for ~$10M average daily dollar volume                    |
| 6 | Sector                     | Exclude Financial, exclude Real Estate | Standard fundamentals don't score cleanly for banks/REITs |
| 7 | EPS (TTM)                  | Positive                      | Profitable last twelve months                                  |
| 8 | Revenue growth (QoQ or YoY)| Positive                      | Growing top line                                               |
| 9 | Debt / Equity              | Under 1                       | Not over-levered                                               |
| 10| Return on Equity           | Positive                      | Actually generating returns on capital                         |

Expected result: **300–600 stocks.** If you get far outside that range,
tighten (>600) or loosen (<300) filter #3 (market cap) or #9 (D/E).

---

## 3. Export the CSV

**On Stockanalysis.com:**
1. Apply all the filters above
2. Scroll to the bottom of the results table
3. Click "Export" or the download icon → CSV
4. The file downloads to your default download location

**On Finviz (workaround for free tier):**
1. Apply filters, set view to 500 rows per page
2. Right-click anywhere on the results table
3. Select "Copy" (or Ctrl+A then Ctrl+C on the table)
4. Open Google Sheets → paste (Ctrl+Shift+V for values only)
5. File → Download → Comma-separated values (.csv)

The file only needs a **Ticker** or **Symbol** column. Company name and Sector
are used in the report if present but are optional.

---

## 4. Drop the file into the repo

Save (or rename) the downloaded file as:

```
input/manual_universe.csv
```

Just overwrite the previous quarter's file. That's the whole update.

---

## 5. Commit and push

```bash
git add input/manual_universe.csv
git commit -m "Quarterly universe refresh $(date +%Y-%m-%d)"
git push
```

The next scheduled Daily Scan (Mon–Fri 22:00 UTC) will automatically:
1. Rebuild `eligible_universe.json` from your new CSV
2. Run the breakout scan
3. Commit the updated universe file, today's report, and history back to the repo

No further action needed. You can also trigger the scan on demand from the
**Actions** tab if you want to see results immediately.

**Optional local test:** if you want to verify the CSV parses cleanly before
pushing, run `python build_universe.py` locally — it takes about a second
and shows the count of unique tickers.

---

## Notes and gotchas

- **Tickers with dots** (BRK.B, BF.B) get auto-normalised to hyphens (BRK-B,
  BF-B) for yfinance compatibility. Nothing you need to do.
- **Missing tickers in yfinance** (recent IPOs, delistings, mispriced small caps)
  are silently skipped during the daily scan and counted in the report's funnel
  as "Skipped (no data)". If you see a large skip count, some of your screened
  tickers may be too obscure for yfinance's coverage — usually fine.
- **Duplicate tickers** in the CSV are automatically deduped on first appearance.
- **Empty rows** are skipped.
- **File encoding** (UTF-8 with or without BOM) is handled automatically.

---

## When you might want to break the routine

- **Major market regime shift** (rate cut cycle starts/ends, sector rotation
  event) — refresh sooner than 3 months to catch newly-viable names.
- **Big earnings season blowups** — a stock that fails your fundamental
  criteria mid-quarter will keep appearing on the scan until the next refresh.
  Not a bug: the trend filter (Layer 4) drops it once price collapses below its
  SMAs. But an off-cycle refresh cleans this up faster.
- **Your Supertrend list changes materially** — if you're now tracking more
  large-caps there, tighten this tool's screen toward mid/small-caps to avoid
  duplicated coverage.
