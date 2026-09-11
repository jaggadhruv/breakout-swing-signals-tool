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
