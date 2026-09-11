"""
build_universe.py

Converts a manually-exported stock list (CSV) into eligible_universe.json
that daily_scan.py consumes.

Run this after every quarterly manual screen:
  python build_universe.py                       # reads input/manual_universe.csv
                                                  # (or the only CSV in input/)
  python build_universe.py path/to/my_export.csv # or point at a specific file

Convention: keep your screener export in the input/ folder as
  input/manual_universe.csv
That way you can just overwrite it each quarter and re-run without arguments.

CSV requirements (all flexible / case-insensitive column names):
  Required:  Ticker  (aliases: Symbol, symbol, ticker)
  Optional:  Company (aliases: Name, security name, company name)
  Optional:  Sector  (aliases: gics sector)
  All other columns are ignored, so you can export whatever you like.

Tickers with dots (e.g. BRK.B) are normalised to hyphens (BRK-B) for yfinance.
Duplicate tickers are collapsed. Blank rows are skipped.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


TICKER_COL_ALIASES = ["ticker", "symbol"]
NAME_COL_ALIASES   = ["name", "company", "company name", "security name"]
SECTOR_COL_ALIASES = ["sector", "gics sector"]

INPUT_DIR       = Path("input")
DEFAULT_CSV     = INPUT_DIR / "manual_universe.csv"
OUTPUT_PATH     = Path("eligible_universe.json")


def find_column(header: list[str], aliases: list[str]) -> int | None:
    lower = [h.lower().strip() for h in header]
    for alias in aliases:
        if alias in lower:
            return lower.index(alias)
    return None


def normalise_ticker(raw: str) -> str:
    return raw.strip().upper().replace(".", "-")


def resolve_csv_path(arg: str | None) -> Path:
    """Pick the CSV to use. Explicit arg wins; else default; else only CSV in input/."""
    if arg:
        return Path(arg)
    if DEFAULT_CSV.exists():
        return DEFAULT_CSV
    # Fallback: single CSV in input/
    if INPUT_DIR.exists():
        csvs = sorted(INPUT_DIR.glob("*.csv"))
        if len(csvs) == 1:
            print(f"Note: using {csvs[0]} (only CSV found in {INPUT_DIR}/).")
            return csvs[0]
        if len(csvs) > 1:
            sys.exit(f"ERROR: multiple CSVs in {INPUT_DIR}/. "
                     f"Rename the one you want to manual_universe.csv, "
                     f"or pass a path explicitly: python build_universe.py <path>")
    return DEFAULT_CSV  # will fail with a clear message downstream


def build(csv_path: Path, output_path: Path) -> None:
    if not csv_path.exists():
        sys.exit(f"ERROR: CSV not found at {csv_path}.\n"
                 f"Export your screen from Stockanalysis/Finviz and save it as "
                 f"{DEFAULT_CSV} (see SCREENING.md for the filter recipe).")

    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            sys.exit(f"ERROR: {csv_path} is empty.")

        ticker_idx = find_column(header, TICKER_COL_ALIASES)
        if ticker_idx is None:
            sys.exit(f"ERROR: CSV needs a Ticker or Symbol column. "
                     f"Found columns: {header}")
        name_idx   = find_column(header, NAME_COL_ALIASES)
        sector_idx = find_column(header, SECTOR_COL_ALIASES)

        seen: set[str] = set()
        eligible: list[dict] = []
        rows_read = 0
        for row in reader:
            rows_read += 1
            if not row or ticker_idx >= len(row):
                continue
            ticker = normalise_ticker(row[ticker_idx])
            if not ticker or ticker in seen:
                continue
            # Basic ticker shape sanity: letters and hyphens only
            if not all(c.isalpha() or c == "-" for c in ticker):
                continue

            name = (row[name_idx].strip()
                    if name_idx is not None and name_idx < len(row)
                    else ticker)
            sector = (row[sector_idx].strip()
                      if sector_idx is not None and sector_idx < len(row)
                      else "Unknown")

            seen.add(ticker)
            eligible.append({
                "ticker": ticker,
                "name": name,
                "sector": sector,
                # piotroski left null — not computed in manual mode.
                # daily_scan handles None cleanly (skips that scoring bonus).
                "piotroski_f_score": None,
            })

    output = {
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "universe_source": f"manual CSV: {csv_path}",
        "eligible_count": len(eligible),
        "eligible": eligible,
    }

    output_path.write_text(json.dumps(output, indent=2))
    print(f"Read {rows_read} rows from {csv_path}.")
    print(f"Wrote {output_path} with {len(eligible)} unique tickers.")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    csv_path = resolve_csv_path(arg)
    build(csv_path, OUTPUT_PATH)


if __name__ == "__main__":
    main()
