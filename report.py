"""
report.py

HTML report generation for daily_scan.py.

Design intent: a trader's terminal read, not a marketing page.
  - High data density, single-column layout, wide-desktop first
  - Restrained palette; color used only for signal (verdict, deltas)
  - System sans for text, monospace for numeric columns (decimal alignment)
  - No cards, no shadows, no gradient chrome — ruled lines and whitespace only
  - Self-contained HTML file, embedded CSS, no external dependencies
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path


VERDICT_LABELS = [
    (7.0, "Favorable"),
    (4.0, "Neutral"),
    (0.0, "Adverse"),
]


def verdict_from_score(score: float) -> str:
    for threshold, label in VERDICT_LABELS:
        if score >= threshold:
            return label
    return "Adverse"


def verdict_color(label: str) -> str:
    return {
        "Favorable": "var(--sig-pos)",
        "Neutral":   "var(--muted)",
        "Adverse":   "var(--sig-neg)",
    }.get(label, "var(--muted)")


# ============================================================================
# CSS — inlined, minimal, deliberate
# ============================================================================

CSS = """
:root {
  --bg:       #FAFAF8;
  --surface:  #FFFFFF;
  --ink:      #1A1A1F;
  --muted:    #6B6B75;
  --rule:     #E4E2DE;
  --rule-strong: #C8C5BF;
  --accent:   #2A4A6B;
  --sig-pos:  #2E7D5B;
  --sig-neg:  #B8402E;
  --sig-warn: #A8862B;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--bg); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 14px; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.container { max-width: 1400px; margin: 0 auto; padding: 32px 24px 48px; }
.mono { font-family: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; }
.num { text-align: right; }
.dim { color: var(--muted); }
.upper { letter-spacing: 0.04em; }

/* Header */
header.masthead {
  border-bottom: 2px solid var(--rule-strong);
  padding-bottom: 20px; margin-bottom: 28px;
}
.masthead-top {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 20px;
}
h1.title { font-size: 22px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
.title-sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
.date-block { text-align: right; }
.date-primary { font-size: 15px; font-weight: 500; }
.date-secondary { font-size: 12px; color: var(--muted); margin-top: 2px; }

/* Breadth panel */
.breadth {
  display: grid; grid-template-columns: 1fr 1fr 2fr;
  gap: 32px; align-items: end;
  padding: 16px 20px;
  background: var(--surface);
  border: 1px solid var(--rule);
}
.breadth-metric .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.breadth-metric .value { font-size: 30px; font-weight: 500; margin-top: 4px; }
.breadth-metric .value .max { font-size: 15px; color: var(--muted); font-weight: 400; }
.breadth-verdict {
  text-align: right;
}
.verdict-tag {
  display: inline-block; padding: 4px 10px;
  font-size: 12px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--surface);
}
.subindicators {
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid var(--rule);
  display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px;
  font-size: 12px;
}
.subindicator .name { color: var(--muted); }
.subindicator .val { margin-top: 2px; font-weight: 500; }

/* Section headings */
h2.section {
  font-size: 12px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted);
  margin: 32px 0 10px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--rule);
}

/* Table */
table.candidates {
  width: 100%; border-collapse: collapse; font-size: 13px;
}
table.candidates thead th {
  text-align: left; font-weight: 600; padding: 8px 10px;
  border-bottom: 1.5px solid var(--rule-strong);
  color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
}
table.candidates thead th.num { text-align: right; }
table.candidates tbody td { padding: 10px; border-bottom: 1px solid var(--rule); }
table.candidates tbody tr:hover { background: rgba(42, 74, 107, 0.04); }
.ticker { font-weight: 600; }
.score { font-weight: 600; }
.score-hi { color: var(--sig-pos); }
.score-mid { color: var(--ink); }
.score-lo { color: var(--muted); }
.patterns { color: var(--muted); font-size: 12px; }
.pattern-tag {
  display: inline-block; margin-right: 4px; padding: 1px 6px;
  border: 1px solid var(--rule-strong); border-radius: 2px;
  font-size: 11px; color: var(--ink); background: var(--surface);
}
.piotroski-hi { color: var(--sig-pos); font-weight: 600; }
.piotroski-mid { color: var(--ink); }
.piotroski-lo { color: var(--sig-neg); }
.streak { color: var(--accent); font-weight: 600; }

/* Two-column secondary */
.secondary { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-top: 24px; }
.sector-list, .funnel-list { list-style: none; padding: 0; margin: 0; }
.sector-list li, .funnel-list li {
  display: flex; justify-content: space-between;
  padding: 8px 0; border-bottom: 1px solid var(--rule);
  font-size: 13px;
}
.sector-list li:last-child, .funnel-list li:last-child { border-bottom: none; }
.funnel-list .step-name { color: var(--muted); }
.funnel-list .step-count { font-weight: 500; }

/* Empty state */
.empty {
  padding: 32px 20px; text-align: center; color: var(--muted);
  background: var(--surface); border: 1px solid var(--rule);
}

/* Methodology */
.methodology { margin-top: 32px; }
details.method-block {
  margin: 6px 0;
  border: 1px solid var(--rule);
  background: var(--surface);
}
details.method-block > summary {
  cursor: pointer;
  padding: 10px 14px;
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  list-style: none;
  position: relative;
}
details.method-block > summary::-webkit-details-marker { display: none; }
details.method-block > summary::before {
  content: "▸";
  display: inline-block;
  width: 14px;
  color: var(--muted);
  font-size: 10px;
  transition: transform 0.15s;
}
details.method-block[open] > summary::before { transform: rotate(90deg); }
details.method-block > summary:hover { color: var(--accent); }
.method-body {
  padding: 4px 14px 14px 28px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--muted);
  border-top: 1px solid var(--rule);
}
.method-body p { margin: 8px 0; }
.method-body strong { color: var(--ink); font-weight: 600; }
.method-body ul { margin: 6px 0; padding-left: 18px; }
.method-body li { margin: 4px 0; }
.method-table {
  width: 100%; border-collapse: collapse;
  margin: 8px 0 12px 0; font-size: 12px;
}
.method-table th, .method-table td {
  padding: 5px 8px; text-align: left;
  border-bottom: 1px solid var(--rule);
}
.method-table th {
  font-weight: 600; color: var(--ink);
  border-bottom: 1.5px solid var(--rule-strong);
  text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em;
}
.method-table td.num { color: var(--ink); }

/* Footer */
footer {
  margin-top: 48px; padding-top: 16px;
  border-top: 1px solid var(--rule);
  font-size: 11px; color: var(--muted);
  display: flex; justify-content: space-between;
}
"""


# ============================================================================
# HTML fragments
# ============================================================================

def _fmt(value, spec: str = "") -> str:
    if value is None or (isinstance(value, float) and (value != value)):
        return "—"
    if spec:
        try:
            return format(value, spec)
        except (ValueError, TypeError):
            return str(value)
    return str(value)


def _score_class(score: float) -> str:
    if score >= 70: return "score score-hi"
    if score >= 40: return "score score-mid"
    return "score score-lo"


def _piotroski_class(p) -> str:
    if p is None: return "dim"
    if p >= 7: return "piotroski-hi"
    if p >= 4: return "piotroski-mid"
    return "piotroski-lo"


def _render_breadth_panel(breadth: dict) -> str:
    weekly = breadth["weekly_score"]
    monthly = breadth["monthly_score"]
    verdict = verdict_from_score(weekly)
    verdict_bg = verdict_color(verdict)

    subs_html = "".join(
        f'<div class="subindicator"><div class="name">{escape(sub["label"])}</div>'
        f'<div class="val mono">{_fmt(sub["value"], ".1f")}<span class="dim"> / 10</span></div></div>'
        for sub in breadth["subindicators"]
    )

    return f"""
<section class="breadth">
  <div class="breadth-metric">
    <div class="label">This Week</div>
    <div class="value mono">{_fmt(weekly, ".1f")}<span class="max"> / 10</span></div>
  </div>
  <div class="breadth-metric">
    <div class="label">This Month</div>
    <div class="value mono">{_fmt(monthly, ".1f")}<span class="max"> / 10</span></div>
  </div>
  <div class="breadth-verdict">
    <div class="label">Environment</div>
    <div style="margin-top:8px;">
      <span class="verdict-tag" style="background:{verdict_bg}">{escape(verdict)}</span>
    </div>
  </div>
</section>
<section class="breadth" style="border-top:none; padding-top:0; padding-bottom:16px;">
  <div style="grid-column: 1 / -1;">
    <div class="subindicators">
      {subs_html}
    </div>
  </div>
</section>
"""


def _render_candidates_table(candidates: list[dict]) -> str:
    if not candidates:
        return '<div class="empty">No breakout signals with setup score ≥ 40 today.</div>'

    rows = []
    for c in candidates:
        pattern_tags = "".join(
            f'<span class="pattern-tag">{escape(p)}</span>' for p in c["pattern_labels"]
        )
        streak_html = (
            f'<span class="streak">×{c["days_on_report"]}</span>'
            if c["days_on_report"] > 1
            else str(c["days_on_report"])
        )
        rr = (c["tp1"] - c["entry"]) / (c["entry"] - c["stop"]) if c["entry"] > c["stop"] else 0

        rows.append(f"""
<tr>
  <td class="ticker">{escape(c["ticker"])}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="patterns">{pattern_tags}</td>
  <td class="num mono">{_fmt(c["entry"], ".2f")}</td>
  <td class="num mono">{_fmt(c["stop"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp1"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp2"], ".2f")}</td>
  <td class="num mono">{_fmt(rr, ".1f")}R</td>
  <td class="num mono {_piotroski_class(c["piotroski"])}">{_fmt(c["piotroski"])}</td>
  <td class="num mono">{streak_html}</td>
  <td class="dim">{escape(c["sector"])}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Ticker</th>
      <th class="num">Score</th>
      <th>Patterns</th>
      <th class="num">Entry</th>
      <th class="num">Stop</th>
      <th class="num">TP1</th>
      <th class="num">TP2</th>
      <th class="num">R:R</th>
      <th class="num">Piotroski</th>
      <th class="num">Streak</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


def _render_sector_breakdown(sector_counts: dict) -> str:
    if not sector_counts:
        return '<div class="dim">No signals to break down.</div>'
    sorted_items = sorted(sector_counts.items(), key=lambda kv: kv[1], reverse=True)
    items = "".join(
        f'<li><span>{escape(sector)}</span><span class="mono">{count}</span></li>'
        for sector, count in sorted_items
    )
    return f'<ul class="sector-list">{items}</ul>'


def _render_funnel(funnel: dict) -> str:
    steps = [
        ("Eligible pool", funnel["eligible"]),
        ("Skipped (no data)", funnel.get("no_data", 0)),
        ("Passed trend filter", funnel["trend_pass"]),
        ("Passed behavioral filter", funnel["behavioral_pass"]),
        ("Breakout signals", funnel["signals"]),
        ("Scored ≥ 40 (shown)", funnel["shown"]),
    ]
    items = "".join(
        f'<li><span class="step-name">{escape(name)}</span>'
        f'<span class="step-count mono">{count}</span></li>'
        for name, count in steps
    )
    return f'<ul class="funnel-list">{items}</ul>'


# ============================================================================
# Methodology block — explains what scores mean and how they're computed
# ============================================================================

def _render_methodology() -> str:
    """Static methodology section. Keep the numeric values in sync with
    SCORING and STOP_* constants in daily_scan.py."""
    return """
<section class="methodology">
  <h2 class="section">Methodology</h2>

  <details class="method-block" open>
    <summary>How the setup score is calculated</summary>
    <div class="method-body">
      <p>Setup score is a composite 0–100+ number. Every triggered component adds points; higher = stronger setup.</p>
      <table class="method-table">
        <thead><tr><th>Component</th><th class="num">Points</th></tr></thead>
        <tbody>
          <tr><td>20-day high (breakout above prior 20-session high)</td><td class="num mono">+10</td></tr>
          <tr><td>55-day high</td><td class="num mono">+20 (added on top of 20-day)</td></tr>
          <tr><td>52-week high (252-day)</td><td class="num mono">+30 (added on top of 20 and 55)</td></tr>
          <tr><td>Horizontal resistance break (tested cluster of swing highs)</td><td class="num mono">+25</td></tr>
          <tr><td>Volatility contraction break (ATR compression → range expansion)</td><td class="num mono">+25</td></tr>
          <tr><td>Volume confirmation bonus</td><td class="num mono">(vol_multiple − 1.5) × 10, capped at +15</td></tr>
          <tr><td>Base length bonus (days consolidating before breakout)</td><td class="num mono">days ÷ 5, capped at +10</td></tr>
          <tr><td>Fundamental quality (Piotroski F-score)</td><td class="num mono">score × 2, capped at +18 (not applied in manual mode)</td></tr>
          <tr><td>Trend context bonus (200 SMA rising AND within 15% of 52W high)</td><td class="num mono">+10</td></tr>
          <tr><td>Multi-day streak bonus (consecutive days on report)</td><td class="num mono">(streak − 1) × 5, capped at +15</td></tr>
        </tbody>
      </table>
      <p><strong>Reading scores.</strong> Only setups scoring ≥40 are shown. As a rough guide:</p>
      <ul>
        <li><strong style="color:var(--muted)">40–59:</strong> Emerging setup. One or two patterns triggered without much confirmation. Worth watching; not a primary trade.</li>
        <li><strong>60–79:</strong> Solid setup. Multiple patterns and/or strong volume, decent base length or streak.</li>
        <li><strong style="color:var(--sig-pos)">80+:</strong> High conviction. Multiple breakout patterns triggering together with volume, base length, and streak confirmation. Rare but strongest historical hit rates.</li>
      </ul>
      <p><strong>Why multi-day streak matters.</strong> The daily-run / weekend-review cadence exists so that stocks appearing 2–3 days in a row get flagged as stronger. First-day breakouts fail often; genuine ones tend to hold and re-appear.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>How market breadth is calculated</summary>
    <div class="method-body">
      <p>Market breadth is the average of 5 sub-indicators, each normalised to 0–10:</p>
      <ul>
        <li><strong>% of eligible pool above 200-day SMA</strong> — linear: 0% → 0, 100% → 10</li>
        <li><strong>% of eligible pool above 50-day SMA</strong> — linear</li>
        <li><strong>New 52-week highs vs new 52-week lows ratio</strong> — 5:1 → 10, 1:1 → 5, 1:5 → 0</li>
        <li><strong>SPY 14-day rate of change</strong> — −5% → 0, 0% → 5, +5% → 10</li>
        <li><strong>VIX (inverted)</strong> — VIX 10 → 10, VIX 40 → 0</li>
      </ul>
      <p><strong>Weekly</strong> = today's snapshot. <strong>Monthly</strong> = 20-day rolling average of daily weekly-scores.</p>
      <p><strong>Verdict thresholds:</strong></p>
      <ul>
        <li><strong style="color:var(--sig-neg)">Adverse (&lt;4):</strong> Broad market weakness. Even good setups fail more often in this regime. Consider standing aside or sizing smaller.</li>
        <li><strong>Neutral (4–7):</strong> Normal environment. Trade setups on their own merits with standard risk management.</li>
        <li><strong style="color:var(--sig-pos)">Favorable (&gt;7):</strong> Broad participation. Higher hit rate on breakouts. Look for setups actively.</li>
      </ul>
    </div>
  </details>

  <details class="method-block">
    <summary>Column reference</summary>
    <div class="method-body">
      <ul>
        <li><strong>Score.</strong> Composite setup quality (see above). Sorted descending.</li>
        <li><strong>Patterns.</strong> Which breakout patterns triggered today. Multiple = stronger.</li>
        <li><strong>Entry.</strong> Today's closing price — your reference entry.</li>
        <li><strong>Stop.</strong> Suggested initial stop-loss. Computed as the tighter of (breakout price × 0.93) or the 20-day swing low. This caps risk near ~7% while still respecting a tight base if one exists.</li>
        <li><strong>TP1 / TP2.</strong> Take-profit targets at 2R and 3R, where R = entry − stop. TP1 is your first partial-exit target; TP2 is the runner target.</li>
        <li><strong>R:R.</strong> Reward-to-risk multiple at TP1. Higher = more attractive risk profile.</li>
        <li><strong>Piotroski.</strong> 0–9 fundamental quality score (green ≥ 7, red ≤ 3). Shown as "—" in manual mode — quality was pre-filtered by your screener.</li>
        <li><strong>Streak.</strong> Number of consecutive days this stock has appeared on the report. "×3" means today is the third consecutive appearance. Higher = more confirmation.</li>
        <li><strong>Sector.</strong> From your screener CSV, or "Unknown" if the column wasn't included.</li>
      </ul>
    </div>
  </details>
</section>
"""


# ============================================================================
# Top-level renderer
# ============================================================================

def render(
    *,
    date_str: str,
    generated_at_utc: str,
    breadth: dict,
    candidates: list[dict],
    sector_counts: dict,
    funnel: dict,
    eligible_refreshed_at: str,
) -> str:
    """Assemble the full HTML report."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Breakout Scan — {escape(date_str)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <header class="masthead">
    <div class="masthead-top">
      <div>
        <h1 class="title">Breakout Swing Scan</h1>
        <div class="title-sub">Discovery from Russell 3000, filtered and ranked.</div>
      </div>
      <div class="date-block">
        <div class="date-primary">{escape(date_str)}</div>
        <div class="date-secondary">Generated {escape(generated_at_utc)}</div>
      </div>
    </div>
    {_render_breadth_panel(breadth)}
  </header>

  <h2 class="section">Ranked Candidates</h2>
  {_render_candidates_table(candidates)}

  <div class="secondary">
    <div>
      <h2 class="section">Sector Distribution</h2>
      {_render_sector_breakdown(sector_counts)}
    </div>
    <div>
      <h2 class="section">Funnel</h2>
      {_render_funnel(funnel)}
    </div>
  </div>

  {_render_methodology()}

  <footer>
    <div>Eligible universe last refreshed: {escape(eligible_refreshed_at)}</div>
    <div>Not investment advice. For personal research use.</div>
  </footer>
</div>
</body>
</html>
"""


def write_report(html: str, reports_dir: Path, date_str: str) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{date_str}.html"
    path.write_text(html, encoding="utf-8")
    return path
