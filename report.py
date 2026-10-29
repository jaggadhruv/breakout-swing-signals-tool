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
  display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px;
  font-size: 12px;
}
/* Liquidity sub-line under each ticker */
.liq { display: block; font-size: 10px; font-weight: 400; color: var(--muted); margin-top: 2px; white-space: nowrap; }
.liq b { font-weight: 600; }
.liq.t-vh b { color: var(--sig-pos); }
.liq.t-h b  { color: #3E7CB1; }
.liq.t-a b  { color: var(--sig-warn); }

/* Multi-section (confluence) highlighting — background on every row of that ticker */
.cf { display: inline-block; margin-left: 6px; padding: 0 5px; border-radius: 3px; font-size: 10px;
      font-weight: 700; color: #fff; vertical-align: 1px; }
.cf.cf2 { background: #7A3DB8; }
.cf.cf3 { background: #C2185B; }
tr.hp td { background: rgba(200, 150, 30, 0.13); }
tr:has(.cf2) > td { background: #EFE3FF; }
tr:has(.cf3) > td { background: #FFDCEB; }
.ldot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: var(--rule-strong); }
.ldot.t-vh { background: var(--sig-pos); } .ldot.t-h { background: #3E7CB1; } .ldot.t-a { background: var(--sig-warn); }

/* Category blocks: guide | today | this week */
.cat { border-radius: 10px; margin: 0 0 22px; border: 1px solid color-mix(in srgb, var(--pc) 35%, transparent);
       background: color-mix(in srgb, var(--pc) 6%, var(--surface)); overflow: hidden; }
.cat-head { background: var(--pc); color: #fff; padding: 10px 16px; display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.cat-head .c-title { font-size: 16px; font-weight: 700; }
.cat-head .c-counts { font-size: 12px; opacity: 0.92; font-family: "SF Mono", Menlo, Consolas, monospace; }
.cat-grid { display: grid; grid-template-columns: 260px 1fr 1fr; gap: 14px; padding: 14px 16px; }
@media (max-width: 1100px) { .cat-grid { grid-template-columns: 1fr; } }
.cat-guide { font-size: 12px; line-height: 1.5; background: color-mix(in srgb, var(--pc) 12%, var(--surface));
             border-radius: 8px; padding: 10px 12px; }
.cat-guide h4 { margin: 0 0 4px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--pc); }
.cat-guide p { margin: 0 0 10px; }
.cat-col { border-radius: 8px; padding: 8px 10px; min-width: 0; }
.cat-col.today { background: var(--surface); border: 2px solid var(--pc); }
.cat-col.week { background: color-mix(in srgb, var(--pc) 10%, var(--surface)); border: 1px dashed var(--pc); }
.cat-col h4 { margin: 0 0 6px; font-size: 12px; color: var(--pc); display: flex; justify-content: space-between; }
.cat-col h4 .n { font-weight: 400; color: var(--muted); }
table.mini { width: 100%; border-collapse: collapse; font-size: 12px; }
table.mini th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted);
                border-bottom: 1px solid var(--rule); padding: 3px 4px; font-weight: 600; }
table.mini td { padding: 4px; border-bottom: 1px solid var(--rule); white-space: nowrap; }
table.mini th.num, table.mini td.num { text-align: right; }
table.mini td.tk { font-weight: 700; }
.setup { display: inline-block; font-size: 10px; padding: 0 5px; border-radius: 3px;
         background: color-mix(in srgb, var(--pc) 16%, transparent); color: var(--ink); }
.more { font-size: 11px; color: var(--muted); margin-top: 4px; }
.avoid { font-size: 11px; margin-top: 8px; color: var(--sig-neg); }
details.detail { border-top: 1px solid color-mix(in srgb, var(--pc) 30%, transparent); padding: 8px 16px 12px; }
details.detail > summary { cursor: pointer; font-size: 12px; font-weight: 600; color: var(--pc); }
details.detail .detail-body { overflow-x: auto; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: 11px; color: var(--muted); margin: -10px 0 22px; align-items: center; }
.legend .sw { display: inline-block; width: 14px; height: 14px; border-radius: 3px; vertical-align: -3px; margin-right: 5px; border: 1px solid var(--rule); }

/* At-a-glance dashboard */
.glance { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 10px; margin: 6px 0 22px; }
.glance a { display: block; text-decoration: none; color: inherit; background: var(--surface);
            border: 1px solid var(--rule); border-top: 4px solid var(--pc); border-radius: 6px; padding: 10px 12px; }
.glance a:hover { border-color: var(--pc); }
.glance .g-title { font-size: 12px; font-weight: 600; }
.glance .g-count { font-size: 24px; font-weight: 700; color: var(--pc); line-height: 1.1; margin-top: 4px; }
.glance .g-count.zero { color: var(--rule-strong); }
.glance .g-sub { font-size: 11px; color: var(--muted); }
.glance .g-top { font-size: 11px; margin-top: 6px; font-weight: 600; color: var(--ink); white-space: nowrap;
                 overflow: hidden; text-overflow: ellipsis; }
.glance a { background: color-mix(in srgb, var(--pc) 8%, var(--surface)); }

/* Strategy panels */
details.panel { background: var(--surface); border: 1px solid var(--rule); border-left: 5px solid var(--pc);
                border-radius: 6px; margin: 0 0 16px; }
details.panel > summary { cursor: pointer; list-style: none; padding: 12px 16px; display: flex; align-items: baseline;
                          gap: 12px; flex-wrap: wrap; background: color-mix(in srgb, var(--pc) 7%, transparent); }
details.panel > summary::-webkit-details-marker { display: none; }
details.panel > summary::before { content: "▸"; color: var(--pc); font-size: 12px; }
details.panel[open] > summary::before { content: "▾"; }
details.panel .p-title { font-size: 15px; font-weight: 700; color: var(--pc); }
details.panel .p-desc { font-size: 12px; color: var(--muted); flex: 1; min-width: 240px; }
details.panel .p-counts { font-size: 12px; font-family: "SF Mono", Menlo, Consolas, monospace; }
details.panel .p-counts b { color: var(--pc); }
details.panel .panel-body { padding: 4px 16px 16px; overflow-x: auto; }
details.panel h3.subsection:first-child { margin-top: 10px; }
details.history { margin-top: 14px; border-top: 1px dashed var(--rule); padding-top: 8px; }
details.history > summary { cursor: pointer; font-size: 12px; font-weight: 600; color: var(--pc); }
details.history[open] > summary { margin-bottom: 6px; }

h3.subsection {
  font-size: 12px; font-weight: 600; margin: 18px 0 8px;
  color: var(--ink); letter-spacing: 0.02em;
}
h3.subsection .count { font-weight: 400; color: var(--muted); }
.tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px;
       border: 1px solid var(--rule); color: var(--muted); }
.tag.pos { color: var(--sig-pos); border-color: var(--sig-pos); }
.tag.neg { color: var(--sig-neg); border-color: var(--sig-neg); }
.tag.warn { color: var(--sig-warn); border-color: var(--sig-warn); }
.tag.hp { background: #C8961E; color: #fff; border-color: #C8961E; font-weight: 600; }
tr.hp td:first-child { box-shadow: inset 3px 0 0 #C8961E; }
.flags { display: block; font-size: 10px; color: var(--muted); margin-top: 2px; line-height: 1.3; }
.subindicator {
  padding: 10px 12px;
  background: var(--panel);
  border-radius: 4px;
  border-left: 3px solid var(--rule);
}
.subindicator.sub-strong { border-left-color: var(--sig-pos); }
.subindicator.sub-mid    { border-left-color: var(--sig-warn); }
.subindicator.sub-weak   { border-left-color: var(--sig-neg); }
.subindicator .name { color: var(--muted); font-size: 11px; }
.subindicator .val { margin-top: 4px; font-weight: 600; font-size: 15px; }
.subindicator .val.sub-strong { color: var(--sig-pos); }
.subindicator .val.sub-mid    { color: var(--sig-warn); }
.subindicator .val.sub-weak   { color: var(--sig-neg); }
.subindicator .interp {
  margin-top: 4px; font-size: 11px; color: var(--muted);
  font-style: italic; line-height: 1.35;
}
@media (max-width: 900px) {
  .subindicators { grid-template-columns: repeat(2, 1fr); }
}

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


def _sub_score_tier(value: float | None) -> str:
    """Return CSS tier class based on 0-10 sub-indicator score.
    Strong (≥7) = green, Mid (4-7) = amber, Weak (<4) = red."""
    if value is None:
        return "sub-mid"
    if value >= 7.0:
        return "sub-strong"
    if value >= 4.0:
        return "sub-mid"
    return "sub-weak"


# One-line, score-tier-aware interpretation for each breadth sub-indicator.
# Keyed on the exact label used in daily_scan.compute_market_breadth so the
# lookup is reliable; falls back to a generic message if the label is unknown.
_SUB_INTERPRETATIONS: dict[str, dict[str, str]] = {
    "% eligible above 200 SMA": {
        "sub-strong": "Broad uptrend — most stocks healthy above long-term trend.",
        "sub-mid":    "Mixed — about half the universe above long-term trend.",
        "sub-weak":   "Broad weakness — most stocks below long-term trend; corrective regime.",
    },
    "% eligible above 50 SMA": {
        "sub-strong": "Short-term momentum is broad — most stocks above 50-day.",
        "sub-mid":    "Mixed short-term participation.",
        "sub-weak":   "Broad short-term pullback — most stocks below 50-day.",
    },
    "New 52W highs vs lows": {
        "sub-strong": "Leadership strong — new highs dominate; risk-on.",
        "sub-mid":    "Balanced highs and lows — no clear leadership tape.",
        "sub-weak":   "Weak tape — more new lows than highs; distribution.",
    },
    "SPY 14-day rate of change": {
        "sub-strong": "SPY posting solid 2-week gains — trend intact.",
        "sub-mid":    "SPY grinding sideways or small gain — no strong direction.",
        "sub-weak":   "SPY in recent decline — momentum has rolled over.",
    },
    "VIX (inverted)": {
        "sub-strong": "Low volatility — market calm (sometimes complacent).",
        "sub-mid":    "Normal volatility — some caution, nothing extreme.",
        "sub-weak":   "Elevated volatility — market stressed; wider stops, size down.",
    },
}


def _sub_interpretation(label: str, value: float | None) -> str:
    tier = _sub_score_tier(value)
    bucket = _SUB_INTERPRETATIONS.get(label)
    if not bucket:
        return ""
    return bucket.get(tier, "")


def _render_breadth_panel(breadth: dict) -> str:
    weekly = breadth["weekly_score"]
    monthly = breadth["monthly_score"]
    verdict = verdict_from_score(weekly)
    verdict_bg = verdict_color(verdict)

    sub_cells = []
    for sub in breadth["subindicators"]:
        tier = _sub_score_tier(sub["value"])
        interp = _sub_interpretation(sub["label"], sub["value"])
        sub_cells.append(
            f'<div class="subindicator {tier}">'
            f'<div class="name">{escape(sub["label"])}</div>'
            f'<div class="val mono {tier}">{_fmt(sub["value"], ".1f")}'
            f'<span class="dim" style="font-weight:400;font-size:11px;"> / 10</span></div>'
            f'<div class="interp">{escape(interp)}</div>'
            f'</div>'
        )
    subs_html = "".join(sub_cells)

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


def _rs_class(rs: float | None) -> str:
    if rs is None: return "dim"
    if rs >= 90: return "piotroski-hi"       # reuse green
    if rs >= 75: return "mono"
    return "dim"


def _render_sector_cell(sector: str, rank: int | None) -> str:
    if not sector:
        return '<span class="dim">—</span>'
    label = escape(sector)
    if rank is None:
        return f'<span class="dim">{label}</span>'
    rank_class = "streak" if rank <= 3 else ("mono" if rank <= 6 else "dim")
    return f'<span class="dim">{label}</span> <span class="{rank_class} mono">#{rank}</span>'


def _render_candidates_table(candidates: list[dict]) -> str:
    if not candidates:
        return '<div class="empty">No breakout signals passing all confluence gates today.</div>'

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
        rs_val = c.get("rs_percentile")
        rs_display = f'P{rs_val:.0f}' if rs_val is not None else '—'
        sector_cell = _render_sector_cell(c.get("sector", ""), c.get("sector_rank"))

        rows.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="patterns">{pattern_tags}</td>
  <td class="num mono">{_fmt(c["entry"], ".2f")}</td>
  <td class="num mono">{_fmt(c["stop"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp1"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp2"], ".2f")}</td>
  <td class="num mono">{_fmt(rr, ".1f")}R</td>
  <td>{_risk_badge(c.get("fake_flags"))}</td>
  <td class="num mono {_rs_class(rs_val)}">{rs_display}</td>
  <td class="num mono {_piotroski_class(c["piotroski"])}">{_fmt(c["piotroski"])}</td>
  <td class="num mono">{streak_html}</td>
  <td>{sector_cell}</td>
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
      <th>Fakeout risk</th>
      <th class="num">RS</th>
      <th class="num">Piotroski</th>
      <th class="num">Streak</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


def _render_recent_quality_table(candidates: list[dict], today_str: str) -> str:
    """Render Recent Quality Breakouts. Each row is one ticker aggregated
    across the archive: peak score, pick date (when the peak fired), total
    appearance count. Entry/stop/TP levels are from the peak signal."""
    if not candidates:
        return ('<div class="empty">No quality breakouts recorded yet. '
                'This section fills in as the tool accumulates history.</div>')

    rows = []
    for c in candidates:
        pattern_tags = "".join(
            f'<span class="pattern-tag">{escape(p)}</span>'
            for p in c.get("peak_patterns", [])
        )
        entry = c.get("peak_entry")
        stop = c.get("peak_stop")
        tp1 = c.get("peak_tp1")
        tp2 = c.get("peak_tp2")
        rr = (
            (tp1 - entry) / (entry - stop)
            if entry and stop and entry > stop else 0
        )

        pick_date = c.get("best_score_date", "")
        date_cell = (
            f'<span class="streak">{escape(pick_date)}</span>'
            if pick_date == today_str
            else f'<span class="dim">{escape(pick_date)}</span>'
        )

        # Seen counter — accent if repeated
        seen = int(c.get("appearances", 1))
        seen_html = (
            f'<span class="streak">×{seen}</span>' if seen >= 3
            else (f'<span class="mono">×{seen}</span>' if seen >= 2
                  else f'<span class="dim mono">×{seen}</span>')
        )

        # Small volume indicator
        vol_mult = float(c.get("max_vol_mult", 0))
        vol_marker = ""
        if vol_mult >= 3.0:
            vol_marker = ' <span class="streak" title="Very high volume">▲▲</span>'
        elif vol_mult >= 2.0:
            vol_marker = ' <span class="dim" title="High volume">▲</span>'

        rows.append(f"""
<tr>
  <td class="mono">{date_cell}</td>
  <td class="ticker">{_tk(c)}</td>
  <td class="num mono">{seen_html}</td>
  <td class="{_score_class(c["best_score"])} num mono">{_fmt(c["best_score"], ".0f")}{vol_marker}</td>
  <td class="patterns">{pattern_tags}</td>
  <td class="num mono">{_fmt(entry, ".2f")}</td>
  <td class="num mono">{_fmt(stop, ".2f")}</td>
  <td class="num mono">{_fmt(tp1, ".2f")}</td>
  <td class="num mono">{_fmt(tp2, ".2f")}</td>
  <td class="num mono">{_fmt(rr, ".1f")}R</td>
  <td class="num mono {_piotroski_class(c.get("piotroski"))}">{_fmt(c.get("piotroski"))}</td>
  <td class="dim">{escape(c.get("sector", ""))}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Pick Date</th>
      <th>Ticker</th>
      <th class="num">Seen</th>
      <th class="num">Best Score</th>
      <th>Patterns</th>
      <th class="num">Entry*</th>
      <th class="num">Stop*</th>
      <th class="num">TP1*</th>
      <th class="num">TP2*</th>
      <th class="num">R:R</th>
      <th class="num">Piotroski</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  * Entry / Stop / TP levels are from the pick date shown (the ticker's peak-scoring signal). Check current price before acting.
  Volume markers: <span class="dim">▲</span> = ≥ 2× avg, <span class="streak">▲▲</span> = ≥ 3× avg.
</p>
"""


def _render_watchlist_table(candidates: list[dict]) -> str:
    """Today's swing-ready watchlist — passed all quality gates, no pattern fired yet.
    Shows pending trigger / stop / TP levels so you can set alerts."""
    if not candidates:
        return ('<div class="empty">No swing-ready watchlist entries today. '
                'All quality-passing tickers either triggered a breakout or are too extended to stalk.</div>')

    rows = []
    for c in candidates:
        rs_val = c.get("rs_percentile")
        rs_display = f'P{rs_val:.0f}' if rs_val is not None else '—'
        sector_cell = _render_sector_cell(c.get("sector", ""), c.get("sector_rank"))
        mom_passes = c.get("momentum_passes", 0)
        mom_display = f'{mom_passes}/4'

        acc_days = c.get("accumulation_days", 0)
        acc_class = "piotroski-hi" if acc_days >= 7 else ("piotroski-mid" if acc_days >= 4 else "dim")

        pct_to = c.get("pct_to_trigger")
        pct_display = f'{pct_to:+.1f}%' if pct_to is not None else '—'
        # Color: close to trigger (<3%) is interesting
        pct_class = "streak" if pct_to is not None and pct_to <= 3 else "mono"

        range_pos = c.get("range_52w_position")
        range_display = f'{range_pos*100:.0f}%' if range_pos is not None else '—'

        rows.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["watchlist_score"])} num mono">{_fmt(c["watchlist_score"], ".0f")}</td>
  <td class="num mono {_rs_class(rs_val)}">{rs_display}</td>
  <td class="num mono">{mom_display}</td>
  <td class="num mono {acc_class}">{acc_days}</td>
  <td class="num mono">{range_display}</td>
  <td class="num mono">{_fmt(c.get("current"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("trigger"), ".2f")}</td>
  <td class="num {pct_class}">{pct_display}</td>
  <td class="num mono">{_fmt(c.get("stop_pending"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("tp1_pending"), ".2f")}</td>
  <td class="num mono {_piotroski_class(c.get("piotroski"))}">{_fmt(c.get("piotroski"))}</td>
  <td>{sector_cell}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Ticker</th>
      <th class="num">Score</th>
      <th class="num">RS</th>
      <th class="num">Mom</th>
      <th class="num">AccDays</th>
      <th class="num">52W%</th>
      <th class="num">Current</th>
      <th class="num">Trigger</th>
      <th class="num">% to Go</th>
      <th class="num">Stop†</th>
      <th class="num">TP1†</th>
      <th class="num">Piotroski</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  † Stop / TP are pending — they only become active once price breaks the Trigger level. Set an alert at the Trigger.
  Mom = momentum confluence passes (RSI 50-75, ADX ≥ 20, Weekly MACD +, 52W pos ≥ 60%). AccDays = IBD-style accumulation days in last 25 sessions (close in upper 25% of day's range with above-average volume).
</p>
"""


def _render_recent_quality_watchlist_table(candidates: list[dict], today_str: str) -> str:
    """Historical quality watchlist — aggregated across the 7-day rolling archive,
    deduped per ticker (peak score wins), composite-ranked for stickiness."""
    if not candidates:
        return ('<div class="empty">No high-quality watchlist entries recorded yet. '
                'This section fills in as the tool accumulates history.</div>')

    rows = []
    for c in candidates:
        pick_date = c.get("best_score_date", "")
        date_cell = (
            f'<span class="streak">{escape(pick_date)}</span>'
            if pick_date == today_str
            else f'<span class="dim">{escape(pick_date)}</span>'
        )
        seen = int(c.get("appearances", 1))
        seen_html = (
            f'<span class="streak">×{seen}</span>' if seen >= 3
            else (f'<span class="mono">×{seen}</span>' if seen >= 2
                  else f'<span class="dim mono">×{seen}</span>')
        )
        rs_val = c.get("peak_rs_percentile")
        rs_display = f'P{rs_val:.0f}' if rs_val is not None else '—'
        sector_cell = _render_sector_cell(c.get("sector", ""), c.get("sector_rank"))
        mom_passes = c.get("peak_momentum_passes", 0)
        acc_days = c.get("peak_accumulation_days", 0)

        rows.append(f"""
<tr>
  <td class="mono">{date_cell}</td>
  <td class="ticker">{_tk(c)}</td>
  <td class="num mono">{seen_html}</td>
  <td class="{_score_class(c["best_score"])} num mono">{_fmt(c["best_score"], ".0f")}</td>
  <td class="num mono {_rs_class(rs_val)}">{rs_display}</td>
  <td class="num mono">{mom_passes}/4</td>
  <td class="num mono">{acc_days}</td>
  <td class="num mono">{_fmt(c.get("peak_current"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("peak_trigger"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("peak_stop_pending"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("peak_tp1_pending"), ".2f")}</td>
  <td class="num mono {_piotroski_class(c.get("piotroski"))}">{_fmt(c.get("piotroski"))}</td>
  <td>{sector_cell}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Pick Date</th>
      <th>Ticker</th>
      <th class="num">Seen</th>
      <th class="num">Best Score</th>
      <th class="num">RS</th>
      <th class="num">Mom</th>
      <th class="num">AccDays</th>
      <th class="num">Current*</th>
      <th class="num">Trigger*</th>
      <th class="num">Stop*†</th>
      <th class="num">TP1*†</th>
      <th class="num">Piotroski</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  * Levels from the pick date (ticker's peak-scoring day). Check current price before setting alerts.
  † Pending levels — active only if price breaks the Trigger.
</p>
"""


def _render_supertrend_table(candidates: list[dict]) -> str:
    """Today's Supertrend-long candidates. Each row is a trend-following entry
    opportunity with a built-in trailing stop (the Supertrend line)."""
    if not candidates:
        return ('<div class="empty">No Supertrend-long candidates passed the elite filter today. '
                'Check Recent Quality Supertrend for recent high-quality flips.</div>')

    rows = []
    for c in candidates:
        rs_val = c.get("rs_percentile")
        rs_display = f'P{rs_val:.0f}' if rs_val is not None else '—'
        sector_cell = _render_sector_cell(c.get("sector", ""), c.get("sector_rank"))
        mom_passes = c.get("momentum_passes", 0)
        acc_days = c.get("accumulation_days", 0)
        acc_class = "piotroski-hi" if acc_days >= 7 else ("piotroski-mid" if acc_days >= 4 else "dim")

        flip_age = c.get("days_since_flip", 0)
        # Fresh flips get accent highlight
        if flip_age <= 1:
            flip_display = f'<span class="streak">{flip_age}d</span>'
        elif flip_age <= 7:
            flip_display = f'<span class="mono">{flip_age}d</span>'
        else:
            flip_display = f'<span class="dim mono">{flip_age}d</span>'

        stop_dist = c.get("stop_distance_pct")
        stop_dist_display = f'{stop_dist:+.1f}%' if stop_dist is not None else '—'

        rows.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["supertrend_score"])} num mono">{_fmt(c["supertrend_score"], ".0f")}</td>
  <td class="num">{flip_display}</td>
  <td class="num mono {_rs_class(rs_val)}">{rs_display}</td>
  <td class="num mono">{mom_passes}/4</td>
  <td class="num mono {acc_class}">{acc_days}</td>
  <td class="num mono">{_fmt(c.get("close"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("supertrend_level"), ".2f")}</td>
  <td class="num mono">{stop_dist_display}</td>
  <td class="num mono {_piotroski_class(c.get("piotroski"))}">{_fmt(c.get("piotroski"))}</td>
  <td>{sector_cell}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Ticker</th>
      <th class="num">Score</th>
      <th class="num">Flip Age</th>
      <th class="num">RS</th>
      <th class="num">Mom</th>
      <th class="num">AccDays</th>
      <th class="num">Current</th>
      <th class="num">ST Stop</th>
      <th class="num">% Above Stop</th>
      <th class="num">Piotroski</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Supertrend (ATR 10, mult 2.5) matches TradingView free tier and your Positional Trading Tool. The ST Stop line trails upward as the trend continues — exit when price closes below it. Flip Age in days since the long signal fired; fresher flips (≤ 3 days) are typically the best risk/reward entries.
</p>
"""


def _render_recent_quality_supertrend_table(candidates: list[dict], today_str: str) -> str:
    """Historical quality Supertrend-long entries aggregated across the 7-day rolling archive."""
    if not candidates:
        return ('<div class="empty">No high-quality Supertrend entries recorded yet. '
                'This section fills in as the tool accumulates history.</div>')

    rows = []
    for c in candidates:
        pick_date = c.get("best_score_date", "")
        date_cell = (
            f'<span class="streak">{escape(pick_date)}</span>'
            if pick_date == today_str
            else f'<span class="dim">{escape(pick_date)}</span>'
        )
        seen = int(c.get("appearances", 1))
        seen_html = (
            f'<span class="streak">×{seen}</span>' if seen >= 3
            else (f'<span class="mono">×{seen}</span>' if seen >= 2
                  else f'<span class="dim mono">×{seen}</span>')
        )
        rs_val = c.get("peak_rs_percentile")
        rs_display = f'P{rs_val:.0f}' if rs_val is not None else '—'
        sector_cell = _render_sector_cell(c.get("sector", ""), c.get("sector_rank"))
        mom_passes = c.get("peak_momentum_passes", 0)
        acc_days = c.get("peak_accumulation_days", 0)
        flip_age = c.get("peak_days_since_flip", 0)

        rows.append(f"""
<tr>
  <td class="mono">{date_cell}</td>
  <td class="ticker">{_tk(c)}</td>
  <td class="num mono">{seen_html}</td>
  <td class="{_score_class(c["best_score"])} num mono">{_fmt(c["best_score"], ".0f")}</td>
  <td class="num mono">{flip_age}d</td>
  <td class="num mono {_rs_class(rs_val)}">{rs_display}</td>
  <td class="num mono">{mom_passes}/4</td>
  <td class="num mono">{acc_days}</td>
  <td class="num mono">{_fmt(c.get("peak_close"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("peak_supertrend_level"), ".2f")}</td>
  <td class="num mono {_piotroski_class(c.get("piotroski"))}">{_fmt(c.get("piotroski"))}</td>
  <td>{sector_cell}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Pick Date</th>
      <th>Ticker</th>
      <th class="num">Seen</th>
      <th class="num">Best Score</th>
      <th class="num">Flip Age*</th>
      <th class="num">RS</th>
      <th class="num">Mom</th>
      <th class="num">AccDays</th>
      <th class="num">Current*</th>
      <th class="num">ST Stop*</th>
      <th class="num">Piotroski</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  * Values from the pick date (ticker's peak-scoring day). Re-check today's chart before acting — the Supertrend trailing stop will have moved since.
</p>
"""


def _render_recovery_table(candidates: list[dict]) -> str:
    """Today's recovery candidates — 20 EMA crossed above 200 EMA from below,
    still within 10% distance (not yet extended), 20 EMA rising."""
    if not candidates:
        return ('<div class="empty">No stocks currently meeting the recovery criteria. '
                'Either no recent 20/200 EMA crossovers, or all recent crossers already moved too far above the 200 EMA.</div>')

    rows = []
    for c in candidates:
        rs_val = c.get("rs_percentile")
        rs_display = f'P{rs_val:.0f}' if rs_val is not None else '—'
        sector_cell = _render_sector_cell(c.get("sector", ""), c.get("sector_rank"))
        mom_passes = c.get("momentum_passes", 0)
        acc_days = c.get("accumulation_days", 0)
        acc_class = "piotroski-hi" if acc_days >= 7 else ("piotroski-mid" if acc_days >= 4 else "dim")

        days_since = c.get("days_since_cross", 999)
        if days_since <= 5:
            cross_display = f'<span class="streak">{days_since}d ago</span>'
        elif days_since <= 15:
            cross_display = f'<span class="mono">{days_since}d ago</span>'
        else:
            cross_display = f'<span class="dim mono">{days_since}d ago</span>'

        dist = c.get("distance_pct", 0)
        if dist <= 3:
            dist_display = f'<span class="streak">{dist:+.1f}%</span>'
        elif dist <= 7:
            dist_display = f'<span class="mono">{dist:+.1f}%</span>'
        else:
            dist_display = f'<span class="dim mono">{dist:+.1f}%</span>'

        rows.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["recovery_score"])} num mono">{_fmt(c["recovery_score"], ".0f")}</td>
  <td class="num">{cross_display}</td>
  <td class="num">{dist_display}</td>
  <td class="num mono {_rs_class(rs_val)}">{rs_display}</td>
  <td class="num mono">{mom_passes}/4</td>
  <td class="num mono {acc_class}">{acc_days}</td>
  <td class="num mono">{_fmt(c.get("close"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("short_ema"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("long_ema"), ".2f")}</td>
  <td class="num mono {_piotroski_class(c.get("piotroski"))}">{_fmt(c.get("piotroski"))}</td>
  <td>{sector_cell}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Ticker</th>
      <th class="num">Score</th>
      <th class="num">Cross Age</th>
      <th class="num">EMA Gap</th>
      <th class="num">RS</th>
      <th class="num">Mom</th>
      <th class="num">AccDays</th>
      <th class="num">Current</th>
      <th class="num">20 EMA</th>
      <th class="num">200 EMA</th>
      <th class="num">Piotroski</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  "Coming out of correction" — 20 EMA just crossed above 200 EMA from below. Looser gates than other sections (RS ≥ 60, sector top 7) because recovery stocks had recent weakness and RS is still rebuilding. Prefer rows with Cross Age ≤ 10 days and EMA Gap ≤ 5% — the stock is still close to the inflection, not yet extended.
</p>
"""


def _render_recent_quality_recovery_table(candidates: list[dict], today_str: str) -> str:
    """Historical quality recovery entries aggregated across the 7-day rolling archive."""
    if not candidates:
        return ('<div class="empty">No high-quality recovery entries recorded yet. '
                'This section fills in as the tool accumulates history.</div>')

    rows = []
    for c in candidates:
        pick_date = c.get("best_score_date", "")
        date_cell = (
            f'<span class="streak">{escape(pick_date)}</span>'
            if pick_date == today_str
            else f'<span class="dim">{escape(pick_date)}</span>'
        )
        seen = int(c.get("appearances", 1))
        seen_html = (
            f'<span class="streak">×{seen}</span>' if seen >= 3
            else (f'<span class="mono">×{seen}</span>' if seen >= 2
                  else f'<span class="dim mono">×{seen}</span>')
        )
        rs_val = c.get("peak_rs_percentile")
        rs_display = f'P{rs_val:.0f}' if rs_val is not None else '—'
        sector_cell = _render_sector_cell(c.get("sector", ""), c.get("sector_rank"))
        mom_passes = c.get("peak_momentum_passes", 0)
        acc_days = c.get("peak_accumulation_days", 0)
        cross_age = c.get("peak_days_since_cross", 0)
        dist = c.get("peak_distance_pct", 0)

        rows.append(f"""
<tr>
  <td class="mono">{date_cell}</td>
  <td class="ticker">{_tk(c)}</td>
  <td class="num mono">{seen_html}</td>
  <td class="{_score_class(c["best_score"])} num mono">{_fmt(c["best_score"], ".0f")}</td>
  <td class="num mono">{cross_age}d</td>
  <td class="num mono">{dist:+.1f}%</td>
  <td class="num mono {_rs_class(rs_val)}">{rs_display}</td>
  <td class="num mono">{mom_passes}/4</td>
  <td class="num mono">{acc_days}</td>
  <td class="num mono">{_fmt(c.get("peak_close"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("peak_short_ema"), ".2f")}</td>
  <td class="num mono {_piotroski_class(c.get("piotroski"))}">{_fmt(c.get("piotroski"))}</td>
  <td>{sector_cell}</td>
</tr>""")

    return f"""
<table class="candidates">
  <thead>
    <tr>
      <th>Pick Date</th>
      <th>Ticker</th>
      <th class="num">Seen</th>
      <th class="num">Best Score</th>
      <th class="num">Cross Age*</th>
      <th class="num">EMA Gap*</th>
      <th class="num">RS</th>
      <th class="num">Mom</th>
      <th class="num">AccDays</th>
      <th class="num">Current*</th>
      <th class="num">20 EMA*</th>
      <th class="num">Piotroski</th>
      <th>Sector</th>
    </tr>
  </thead>
  <tbody>{"".join(rows)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  * Values from the pick date (ticker's peak-scoring day). Re-check today's chart — the 20 EMA will have moved since.
</p>
"""


def _empty(msg: str) -> str:
    return f'<div class="empty">{escape(msg)}</div>'


def _rs_cell(rs_val) -> str:
    disp = f"P{rs_val:.0f}" if rs_val is not None else "—"
    return f'<td class="num mono {_rs_class(rs_val)}">{disp}</td>'


def _yes(flag: bool, label: str) -> str:
    return f'<span class="tag pos">{escape(label)}</span>' if flag else '<span class="dim">—</span>'


def _money(v: float | None) -> str:
    if v is None:
        return "—"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"${v / div:.1f}{suf}"
    return f"${v:.0f}"


def _shares(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K"


def _liq_html(c: dict) -> str:
    """Liquidity levels: tier, avg shares/day, avg $/day, 1% of ADV (size ceiling)."""
    lq = c.get("liquidity")
    if not lq:
        return ""
    cls = {"Very high": "t-vh", "High": "t-h", "Adequate": "t-a"}.get(lq["tier"], "")
    tip = (f"Liquidity {lq['tier']}: avg {_shares(lq['avg_vol'])} shares/day, "
           f"{_money(lq['avg_dollar_vol'])}/day. Keeping a position under 1% of ADV "
           f"({_money(lq['one_pct_adv'])}) avoids moving the price.")
    return (f'<span class="liq {cls}" title="{escape(tip)}"><b>{escape(lq["tier"])}</b> · '
            f'{_shares(lq["avg_vol"])} sh · {_money(lq["avg_dollar_vol"])}/d · 1% ADV {_money(lq["one_pct_adv"])}</span>')


def _cf_badge(c: dict) -> str:
    """Badge for tickers appearing in 2+ sections today (row background via CSS :has)."""
    secs = c.get("confluence") or []
    if len(secs) < 2:
        return ""
    cls = "cf3" if len(secs) >= 3 else "cf2"
    return f'<span class="cf {cls}" title="In {len(secs)} sections today: {escape(", ".join(secs))}">×{len(secs)} sections</span>'


def _tk(c: dict, compact: bool = False) -> str:
    if compact:
        lq = c.get("liquidity") or {}
        dot = {"Very high": "t-vh", "High": "t-h", "Adequate": "t-a"}.get(lq.get("tier"), "")
        dot_html = (f'<span class="ldot {dot}" title="Liquidity {escape(lq.get("tier", ""))}: '
                    f'{_money(lq.get("avg_dollar_vol"))}/day, 1% ADV {_money(lq.get("one_pct_adv"))}"></span>') if lq else ""
        return f'{dot_html}{escape(c["ticker"])}{_cf_badge(c)}'
    return f'{escape(c["ticker"])}{_cf_badge(c)}{_liq_html(c)}'


_SETUP_LABELS = {"support": "Near support", "resistance": "Near resistance", "retest": "Break & retest", "holding": "Holding above BO",
                 "reversal": "Reversal", "mtf_rsi": "MTF RSI", "positional": "Positional"}


def _render_setup_history_table(rows: list[dict], today_str: str) -> str:
    """7-day quality list for setup types stored in setups_archive.json."""
    if not rows:
        return _empty("No names have reached the quality bar in this section over the past 7 days yet. "
                      "This list fills in as daily runs accumulate.")
    body = []
    for c in rows:
        tr_cls, star = _hp_attrs(c)
        pick = c.get("best_score_date", "")
        date_cell = (f'<span class="streak">{escape(pick)}</span>' if pick == today_str
                     else f'<span class="dim">{escape(pick)}</span>')
        seen = int(c.get("appearances", 1))
        body.append(f"""
<tr{tr_cls}>
  <td class="mono">{date_cell}</td>
  <td><span class="tag">{escape(_SETUP_LABELS.get(c["setup"], c["setup"]))}</span></td>
  <td class="ticker">{_tk(c)}{star}</td>
  <td class="num mono">{'<span class="streak">' if seen >= 3 else ''}×{seen}{'</span>' if seen >= 3 else ''}</td>
  <td class="{_score_class(c["best_score"])} num mono">{_fmt(c["best_score"], ".0f")}</td>
  <td class="num mono">{_fmt(c.get("close"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("level"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("stop"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("target"), ".2f")}</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Pick date</th><th>Setup</th><th>Ticker</th><th class="num">Seen</th><th class="num">Best score</th>
    <th class="num">Close*</th><th class="num">Level / entry*</th><th class="num">Stop*</th>
    <th class="num">Target*</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">* From the ticker's best-scoring day this week. Re-check today's chart before acting.
Liquidity shown is today's.</p>
"""


def _pct(v: float | None, digits: int = 0) -> str:
    return "—" if v is None else f"{v * 100:.{digits}f}%"


def _render_positional_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No financially strong, fairly valued, non-extended names today "
                      "(or fundamentals are still being cached; this fills in over the first few runs).")
    body = []
    for c in rows:
        val_cls = "pos" if c["valuation_label"] == "Undervalued" else ""
        peg = "—" if c.get("peg_used") is None else f'{c["peg_used"]:.2f}'
        de = "—" if c.get("debt_to_equity") is None else f'{c["debt_to_equity"] / 100:.2f}×'
        body.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td><span class="tag {val_cls}">{escape(c["valuation_label"])}</span></td>
  <td class="num mono">{_fmt(c.get("forward_pe"), ".1f")}</td>
  <td class="num mono">{peg}</td>
  <td class="num mono">{_pct(c.get("fcf_yield"), 1)}</td>
  <td class="num mono">{_pct(c.get("roe"))}</td>
  <td class="num mono">{_pct(c.get("profit_margin"))}</td>
  <td class="num mono">{_pct(c.get("revenue_growth"))}</td>
  <td class="num mono">{de}</td>
  <td class="num mono">{_money(c.get("market_cap"))}</td>
  <td class="num mono">+{c["pct_above_200"]:.1f}%</td>
  <td class="num mono">{c["rsi"]:.0f}</td>
  <td class="num mono">{_fmt(c["close"], ".2f")}</td>
  <td class="num mono">{_fmt(c["sma50"], ".2f")}</td>
  <td class="num mono">{_fmt(c["stop"], ".2f")}</td>
  <td class="num mono">{_fmt(c["target"], ".2f")}</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th class="num">Score</th><th>Valuation</th><th class="num">Fwd P/E</th><th class="num">PEG</th>
    <th class="num">FCF yield</th><th class="num">ROE</th><th class="num">Net margin</th><th class="num">Rev growth</th>
    <th class="num">Debt/Eq</th><th class="num">Mkt cap</th><th class="num">vs 200 SMA</th><th class="num">RSI</th>
    <th class="num">Current</th><th class="num">Add zone (50 SMA)</th><th class="num">Stop</th>
    <th class="num">Target</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Positional ideas (weeks to months): profitable, cash-generative, moderately levered companies at PEG ≤ 2 (or forward P/E ≤ 30
  when PEG is unavailable), in a long-term uptrend but not stretched: ≤ 15% above the 200 SMA, ≤ 8% above the 50 SMA, RSI ≤ 65.
  Add zone = the 50 SMA, where pullbacks often find buyers. Stop = 3% under the 200 SMA. Target = 52-week high (or +20%).
  Fundamentals come from Yahoo Finance (refreshed weekly) and can be stale or wrong: verify in the company's filings before
  committing capital.
</p>
"""


def _risk_badge(flags: list[str] | None) -> str:
    """Fake-breakout risk: 0 flags = Clean, 1 = Caution, 2+ = High risk."""
    flags = flags or []
    if not flags:
        return '<span class="tag pos">Clean</span>'
    cls, label = ("warn", "Caution") if len(flags) == 1 else ("neg", "High risk")
    return (f'<span class="tag {cls}" title="{escape("; ".join(flags))}">{label}</span>'
            f'<span class="flags">{escape(" · ".join(flags))}</span>')


def _hp_attrs(row: dict) -> tuple[str, str]:
    """(tr class attribute, star badge) for high-probability rows."""
    if row.get("high_probability"):
        return ' class="hp"', ' <span class="tag hp">★ High prob</span>'
    return "", ""


def _render_support_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No quality stocks within 3% of a tested support level today.")
    body = []
    for c in rows:
        tr_cls, star = _hp_attrs(c)
        body.append(f"""
<tr{tr_cls}>
  <td class="ticker">{_tk(c)}{star}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="num mono">{_fmt(c["close"], ".2f")}</td>
  <td class="num mono">{_fmt(c["level"], ".2f")}</td>
  <td class="num mono">{c["distance_pct"]:.1f}%</td>
  <td class="num mono">×{c["touches"]}</td>
  <td class="num">{_yes(c.get("sma50_confluence"), "50 SMA")}</td>
  <td class="num">{_yes(c.get("dry_up"), "Dry-up")}</td>
  {_rs_cell(c.get("rs_percentile"))}
  <td class="num mono">{_fmt(c.get("stop"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("target"), ".2f")}</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th class="num">Score</th><th class="num">Current</th><th class="num">Support</th>
    <th class="num">Above by</th><th class="num">Touches</th><th class="num">Confluence</th>
    <th class="num">Volume</th><th class="num">RS</th><th class="num">Stop</th>
    <th class="num">Target (resistance)</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Buy-the-dip candidates: price is resting just above a horizontal level tested ≥ 2 times, inside a rising 200 SMA uptrend.
  Wait for a bounce candle off the level before entering. Stop = 3% below support; target = next resistance.
  Dry-up = last 5 sessions' volume &lt; 80% of the prior 20 (sellers exhausting).
  <span class="tag hp">★ High prob</span> = this support is an old resistance the stock just broke out of (see Recent Breakouts &amp; Retests).
</p>
"""


def _render_resistance_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No quality stocks within 3% below a tested resistance level today.")
    body = []
    for c in rows:
        acc = c.get("accumulation_days", 0)
        acc_class = "piotroski-hi" if acc >= 7 else ("piotroski-mid" if acc >= 4 else "dim")
        body.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="num mono">{_fmt(c["close"], ".2f")}</td>
  <td class="num mono">{_fmt(c["level"], ".2f")}</td>
  <td class="num mono">{c["distance_pct"]:.1f}%</td>
  <td class="num mono">×{c["touches"]}</td>
  <td class="num">{_yes(c.get("dry_up"), "Tightening")}</td>
  {_rs_cell(c.get("rs_percentile"))}
  <td class="num mono">{c.get("momentum_passes", 0)}/4</td>
  <td class="num mono {acc_class}">{acc}</td>
  <td class="num mono">{_fmt(c.get("support_below"), ".2f")}</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th class="num">Score</th><th class="num">Current</th><th class="num">Resistance</th>
    <th class="num">Below by</th><th class="num">Touches</th><th class="num">Volume</th>
    <th class="num">RS</th><th class="num">Mom</th><th class="num">AccDays</th>
    <th class="num">Support below</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Breakout candidates pressing a ceiling tested ≥ 2 times. Set an alert at the Resistance level and only act on a close above it
  with volume ≥ 1.5× average. Tightening = volume contracting under the level (supply drying up, VCP-like).
</p>
"""


def _render_retest_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No recent breakouts are currently retesting their breakout level.")
    body = []
    for c in rows:
        bounce = '<span class="tag pos">Bounce today</span>' if c.get("bounce_today") else '<span class="dim">Testing</span>'
        tr_cls, star = _hp_attrs(c)
        body.append(f"""
<tr{tr_cls}>
  <td class="ticker">{_tk(c)}{star}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="num mono">{c["breakout_age"]}d ago</td>
  <td class="num mono">{_fmt(c["breakout_level"], ".2f")}</td>
  <td class="num mono">{c["breakout_vol_mult"]:.1f}×</td>
  <td class="num mono">{_fmt(c["post_high"], ".2f")}</td>
  <td class="num mono">−{c["pullback_pct"]:.1f}%</td>
  <td class="num mono">{_fmt(c["close"], ".2f")}</td>
  <td class="num">{bounce}</td>
  <td class="num mono">×{c.get("resistance_touches", 0)}</td>
  <td>{_risk_badge(c.get("fake_flags"))}</td>
  {_rs_cell(c.get("rs_percentile"))}
  <td class="num mono">{_fmt(c.get("stop"), ".2f")}</td>
  <td class="num mono">{_fmt(c.get("tp1"), ".2f")}</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th class="num">Score</th><th class="num">Broke out</th><th class="num">BO level</th>
    <th class="num">BO volume</th><th class="num">Post-BO high</th><th class="num">Pullback</th>
    <th class="num">Current</th><th class="num">Status</th><th class="num">Prior tests</th>
    <th>Fakeout risk</th><th class="num">RS</th>
    <th class="num">Stop</th><th class="num">TP1 (2R)</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Break &amp; retest: the stock broke a 55-session high on volume, ran, then pulled back to the old breakout level and is holding it
  (old resistance acting as new support). "Bounce today" = closed up from the retest, the confirmation many traders wait for.
  Stop = 2% below the lower of the retest low or breakout level. Prior tests = swing highs at this level before the breakout.
</p>
"""


def _render_holding_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No other recent breakouts holding above their level.")
    body = []
    for c in rows:
        ext = c["extension_pct"]
        ext_html = (f'<span class="mono" style="color:var(--sig-neg);font-weight:600;">+{ext:.1f}%</span>' if ext > 10
                    else f'<span class="mono">+{ext:.1f}%</span>')
        body.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="num mono">{c["breakout_age"]}d ago</td>
  <td class="num mono">{_fmt(c["breakout_level"], ".2f")}</td>
  <td class="num mono">{c["breakout_vol_mult"]:.1f}×</td>
  <td class="num mono">{_fmt(c["close"], ".2f")}</td>
  <td class="num">{ext_html}</td>
  <td class="num mono">−{c["pullback_pct"]:.1f}%</td>
  <td>{_risk_badge(c.get("fake_flags"))}</td>
  {_rs_cell(c.get("rs_percentile"))}
  <td class="num mono">{c.get("momentum_passes", 0)}/4</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th class="num">Score</th><th class="num">Broke out</th><th class="num">BO level</th>
    <th class="num">BO volume</th><th class="num">Current</th><th class="num">Above level</th>
    <th class="num">Off high</th><th>Fakeout risk</th><th class="num">RS</th><th class="num">Mom</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Breakouts from the last 20 sessions that have not retested yet. Above level &gt; 10% (red) = extended; avoid chasing and
  wait for these to move into the Break &amp; Retest table. Failed breakouts (closed &gt; 3% back below the level) are excluded.
</p>
"""


def _render_high_prob_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No high-probability retests today (needs: old resistance tested ≥ 2×, broken on volume, "
                      "retested as support, bounce today, zero fakeout flags).")
    return _render_retest_table(rows)


def _render_fake_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No recent breakouts have failed among quality names.")
    body = []
    for c in rows:
        status = ('<span class="tag neg">Failed</span>' if c["status"] == "failed"
                  else '<span class="tag warn">Failing</span>')
        body.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td>{status}</td>
  <td class="num mono">{c["breakout_age"]}d ago</td>
  <td class="num mono">{_fmt(c["breakout_level"], ".2f")}</td>
  <td class="num mono">{_fmt(c["post_high"], ".2f")}</td>
  <td class="num mono">{_fmt(c["close"], ".2f")}</td>
  <td class="num mono" style="color:var(--sig-neg);">{c["extension_pct"]:+.1f}%</td>
  <td class="num mono">{c["breakout_vol_mult"]:.1f}×</td>
  <td><span class="flags" style="font-size:11px;">{escape(" · ".join(c.get("fake_flags", [])))}</span></td>
  {_rs_cell(c.get("rs_percentile"))}
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th>Status</th><th class="num">Broke out</th><th class="num">BO level</th>
    <th class="num">Post-BO high</th><th class="num">Current</th><th class="num">vs level</th>
    <th class="num">BO volume</th><th>Why it looks fake</th><th class="num">RS</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Avoid list. Failed = closed &gt; 3% back below the breakout level; Failing = back below it by less than 3%.
  If you hold one of these, the breakout thesis is broken: tighten or exit. A later reclaim of the level can be re-evaluated fresh.
</p>
"""


def _render_mtf_rsi_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No stocks with monthly & weekly RSI > 60 and a fresh daily RSI bounce above 50 on good volume today.")
    body = []
    for c in rows:
        age = c["cross_age"]
        age_html = '<span class="streak">today</span>' if age == 0 else f'<span class="mono">{age}d ago</span>'
        acc = c.get("accumulation_days", 0)
        acc_class = "piotroski-hi" if acc >= 7 else ("piotroski-mid" if acc >= 4 else "dim")
        body.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="num mono score-hi">{c["monthly_rsi"]:.0f}</td>
  <td class="num mono score-hi">{c["weekly_rsi"]:.0f}</td>
  <td class="num mono">{c["daily_rsi_dip"]:.0f} → {c["daily_rsi"]:.0f}</td>
  <td class="num">{age_html}</td>
  <td class="num mono">{c["cross_vol_mult"]:.1f}×</td>
  <td class="num mono {acc_class}">{acc}</td>
  {_rs_cell(c.get("rs_percentile"))}
  <td class="num mono">{_fmt(c["entry"], ".2f")}</td>
  <td class="num mono">{_fmt(c["stop"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp1"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp2"], ".2f")}</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th class="num">Score</th><th class="num">Monthly RSI</th><th class="num">Weekly RSI</th>
    <th class="num">Daily RSI dip → now</th><th class="num">Crossed 50</th><th class="num">Cross-day vol</th>
    <th class="num">AccDays</th><th class="num">RS</th><th class="num">Entry</th><th class="num">Stop</th>
    <th class="num">TP1 (2R)</th><th class="num">TP2 (3R)</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Higher-timeframe momentum intact (monthly and weekly RSI(14) &gt; 60) while the daily RSI dipped below 50 and has just
  crossed back above it on at least average volume: the short-term pullback is ending inside a strong trend.
  Stop = 1% under the 10-session low. Monthly RSI uses the in-progress month, as TradingView does.
</p>
"""


def _render_reversal_table(rows: list[dict]) -> str:
    if not rows:
        return _empty("No pullback-reversal triggers in quality uptrends today.")
    body = []
    for c in rows:
        body.append(f"""
<tr>
  <td class="ticker">{_tk(c)}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td><span class="tag pos">{escape(c["trigger"])}</span></td>
  <td class="num mono">−{c["pullback_pct"]:.1f}%</td>
  <td class="num mono">{c["rsi_min5"]:.0f} → {c["rsi_now"]:.0f}</td>
  <td class="num">{_yes(c.get("near_sma50"), "50 SMA")}</td>
  <td class="num mono">{_fmt(c.get("today_vol_mult"), ".1f")}×</td>
  {_rs_cell(c.get("rs_percentile"))}
  <td class="num mono">{_fmt(c["entry"], ".2f")}</td>
  <td class="num mono">{_fmt(c["stop"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp1"], ".2f")}</td>
  <td class="num mono">{_fmt(c["high20"], ".2f")}</td>
  <td>{_render_sector_cell(c.get("sector", ""), c.get("sector_rank"))}</td>
</tr>""")
    return f"""
<table class="candidates">
  <thead><tr>
    <th>Ticker</th><th class="num">Score</th><th>Trigger</th><th class="num">Pullback</th>
    <th class="num">RSI low → now</th><th class="num">Support</th><th class="num">Vol</th>
    <th class="num">RS</th><th class="num">Entry</th><th class="num">Stop</th>
    <th class="num">TP1 (2R)</th><th class="num">Prior high</th><th>Sector</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
</table>
<p class="dim" style="font-size:11px;margin-top:6px;">
  Pullback-in-uptrend reversals: price above the 200 SMA, down 5–25% from its 20-day high, RSI dipped to ≤ 40, and today printed
  a bullish reversal candle. Stop = just under the 5-day low. Prior high = natural target. Counter-trend on the short timeframe,
  so size smaller than for breakouts.
</p>
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
    min_score = funnel.get("min_show_score_used", 40)
    bo_cap = funnel.get("max_breakouts_cap", 5)
    wl_cap = funnel.get("max_watchlist_cap", 8)
    st_cap = funnel.get("max_supertrend_cap", 6)
    steps = [
        ("Eligible pool", funnel["eligible"]),
        ("Skipped (no data)", funnel.get("no_data", 0)),
        (f"Dropped by liquidity filter (price ≥ ${funnel.get('min_price', 10):.0f}, vol ≥ {funnel.get('min_avg_volume', 500000)/1e3:.0f}K, $vol ≥ ${funnel.get('min_avg_dollar_volume', 1e7)/1e6:.0f}M)", funnel.get("illiquid", 0)),
        ("Passed trend filter", funnel["trend_pass"]),
        ("Passed behavioral filter", funnel["behavioral_pass"]),
        ("Passed momentum confluence", funnel.get("momentum_pass", 0)),
        ("— Pattern triggered (→ breakouts)", funnel.get("pattern_pass", funnel.get("signals", 0))),
        ("— No pattern yet (→ watchlist pool)", funnel.get("watchlist_raw", 0)),
        ("— Supertrend long state (→ supertrend pool)", funnel.get("supertrend_raw", 0)),
        ("— 20/200 EMA recovery (→ recovery pool)", funnel.get("recovery_raw", 0)),
        ("Dropped by RS gate (breakouts)", funnel.get("rs_gated", 0)),
        ("Dropped by sector gate (breakouts)", funnel.get("sector_gated", 0)),
        ("Final breakout signals (archived)", funnel["signals"]),
        ("Final watchlist entries (archived)", funnel.get("watchlist_signals", 0)),
        ("Final supertrend entries (archived)", funnel.get("supertrend_signals", 0)),
        ("Final recovery entries (archived)", funnel.get("recovery_signals", 0)),
        ("Elite breakouts qualified", funnel.get("elite_breakouts", 0)),
        ("Elite watchlist qualified", funnel.get("elite_watchlist", 0)),
        ("Elite supertrend qualified (fresh ≤ {}d flip)".format(funnel.get("supertrend_max_flip_age_days", 20)), funnel.get("elite_supertrend", 0)),
        ("Recovery qualified (looser gates: RS≥60, sec≤7)", funnel.get("qualified_recovery", 0)),
        (f"Breakouts shown (top {bo_cap})", funnel["shown"]),
        (f"Watchlist shown (top {wl_cap})", funnel.get("watchlist_shown", 0)),
        (f"Supertrend shown (top {st_cap})", funnel.get("supertrend_shown", 0)),
        (f"Recovery shown (top {funnel.get('max_recovery_cap', 6)})", funnel.get("recovery_shown", 0)),
        ("Quality base (behavioral + above rising 200 SMA)", funnel.get("quality_base_pass", 0)),
        ("— Near support / resistance (raw)", funnel.get("sr_raw", 0)),
        ("— Recent breakouts not failed (raw)", funnel.get("retest_raw", 0)),
        ("— Reversal candle triggers (raw)", funnel.get("reversal_raw", 0)),
        ("Support: gated → qualified → shown", f'{funnel.get("support_signals", 0)} → {funnel.get("support_qualified", 0)} → {funnel.get("support_shown", 0)}'),
        ("Resistance: gated → qualified → shown", f'{funnel.get("resistance_signals", 0)} → {funnel.get("resistance_qualified", 0)} → {funnel.get("resistance_shown", 0)}'),
        ("Break & retest: gated → qualified → shown", f'{funnel.get("retest_signals", 0)} → {funnel.get("retest_qualified", 0)} → {funnel.get("retest_shown", 0)}'),
        ("Holding above: gated → qualified → shown", f'{funnel.get("holding_signals", 0)} → {funnel.get("holding_qualified", 0)} → {funnel.get("holding_shown", 0)}'),
        ("★ High-probability retests shown", funnel.get("high_prob_shown", 0)),
        ("Fake / failed breakouts: gated → shown", f'{funnel.get("fake_signals", 0)} → {funnel.get("fake_shown", 0)}'),
        ("MTF RSI: raw → gated → qualified → shown", f'{funnel.get("mtf_rsi_raw", 0)} → {funnel.get("mtf_rsi_signals", 0)} → {funnel.get("mtf_rsi_qualified", 0)} → {funnel.get("mtf_rsi_shown", 0)}'),
        ("Positional: candidates → no fundamentals → pass → shown", f'{funnel.get("positional_raw", 0)} → {funnel.get("positional_no_data", 0)} → {funnel.get("positional_signals", 0)} → {funnel.get("positional_shown", 0)}'),
        ("Reversal: gated → qualified → shown", f'{funnel.get("reversal_signals", 0)} → {funnel.get("reversal_qualified", 0)} → {funnel.get("reversal_shown", 0)}'),
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

  <details class="method-block">
    <summary>Confluence layer (gates applied before any signal reaches the report)</summary>
    <div class="method-body">
      <p>Every signal must survive three independent gates in addition to the pattern checks. The idea is to filter out breakouts that lack supporting context — momentum, relative strength, or sector tailwinds.</p>
      <p><strong>Gate 1 — Momentum confluence.</strong> At least 3 of 4 must hold:</p>
      <ul>
        <li><strong>RSI(14) in 50–75</strong> — strong but not extended</li>
        <li><strong>ADX(14) ≥ 20</strong> — stock is actually trending, not chopping</li>
        <li><strong>Weekly MACD histogram positive</strong> — higher-timeframe alignment</li>
        <li><strong>Price in top 40% of 52-week range</strong> — already in a strength regime</li>
      </ul>
      <p><strong>Gate 2 — Relative Strength percentile.</strong> Each stock's 12-week return minus SPY's 12-week return is percentile-ranked across the eligible pool. Only tickers in the top 25% (RS ≥ 75) pass. Tickers in the top 10% (RS ≥ 90) get a <strong>+10 scoring bonus</strong>. This is the single most predictive filter for breakout follow-through.</p>
      <p><strong>Gate 3 — Sector regime.</strong> The 11 Sector SPDR ETFs (XLK, XLV, XLF, …) are ranked by 60-day return vs SPY. Only tickers whose sector ranks in the top 6 of 11 pass. Top-3 sectors award a <strong>+5 scoring bonus</strong>. Unmapped sectors (e.g., "Unknown") pass by default.</p>
      <p><strong>Market regime adjustment.</strong> When weekly breadth is Adverse (&lt; 4), the minimum shown score is raised from 40 to 75 — only the strongest setups surface during broad weakness.</p>
      <p><strong>Hidden bonus.</strong> If all 4 momentum checks pass (not just 3), the setup earns an additional <strong>+5 scoring bonus</strong>.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>How Recent Quality Breakouts is ranked</summary>
    <div class="method-body">
      <p>The Recent Quality Breakouts section aggregates every signal from the past 7 days (rolling week, same rollover cadence as the Positional Trading Tool), then picks the top 10 by a composite <strong>keep score</strong>:</p>
      <table class="method-table">
        <thead><tr><th>Component</th><th class="num">Contribution</th></tr></thead>
        <tbody>
          <tr><td>Ticker's best score ever achieved (base)</td><td class="num mono">full value</td></tr>
          <tr><td>Recency bonus (latest appearance)</td><td class="num mono">+15 within 7 days, +5 within 21 days, 0 older</td></tr>
          <tr><td>Appearance bonus (times seen in archive)</td><td class="num mono">+2 per appearance, capped at +15</td></tr>
          <tr><td>Volume bonus (max multiple observed)</td><td class="num mono">+5 if ≥ 2× avg, +10 if ≥ 3× avg</td></tr>
        </tbody>
      </table>
      <p><strong>Eligibility:</strong> ticker's peak score must be ≥ 60 (the "solid setup" tier). Fresh tickers hitting 60+ enter the ranking; low-quality signals never do.</p>
      <p><strong>Effect of the composite:</strong></p>
      <ul>
        <li><strong>High-conviction stays sticky.</strong> A 90-score signal from three weeks ago still outranks a 65-score fresh signal.</li>
        <li><strong>Repeat winners rise.</strong> A ticker seen 6 times climbs above one-offs, all else equal.</li>
        <li><strong>Volume-confirmed setups get priority</strong> over low-volume ones at the same score.</li>
        <li><strong>Recency still matters</strong> — but as a tiebreaker, not a dominant factor.</li>
      </ul>
      <p><strong>Row data:</strong> the <strong>Pick Date</strong> is when the ticker's best score fired; <strong>Seen</strong> is total appearances in the archive; Entry / Stop / TPs are from that peak signal. Always sanity-check the current price against these — they can be days or weeks old.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>How "today's" sections are curated (elite filter + caps)</summary>
    <div class="method-body">
      <p>The two "today" sections (Breakouts and Watchlist) are deliberately kept small so you can review in minutes, not hours. Every candidate that passes the base gates still gets archived — but only elite ones display today.</p>
      <p><strong>Elite filter — must pass ALL to display today:</strong></p>
      <table class="method-table">
        <thead><tr><th>Criterion</th><th>Threshold</th></tr></thead>
        <tbody>
          <tr><td>RS percentile</td><td class="mono">≥ 85 (top 15%, vs base gate 75)</td></tr>
          <tr><td>Momentum confluence passes</td><td class="mono">4 of 4 (vs base gate 3)</td></tr>
          <tr><td>Sector rank</td><td class="mono">≤ 4 (top 4 sectors, vs base gate 6)</td></tr>
          <tr><td>Accumulation days (watchlist only)</td><td class="mono">≥ 5</td></tr>
          <tr><td>Base score threshold</td><td class="mono">unchanged (40 or 75 in Adverse)</td></tr>
        </tbody>
      </table>
      <p><strong>Display caps:</strong> Breakouts max 5 rows, Watchlist max 8 rows. If more candidates qualify, the top ones by score win. If none qualify (common in weak markets), the section is empty and you fall back to the Recent Quality sections for broader context.</p>
      <p><strong>What this fixes:</strong> too many names to review wasted time and encouraged skimming. 5 breakouts and 8 watchlist entries is small enough to study each one properly, understand its chart, and make a real trade/no-trade decision. Everything below elite still accrues in the 7-day rolling archives — nothing is lost from this week, just not surfaced for daily review.</p>
      <p><strong>If this feels too strict:</strong> on a strong market day, 8-10 names may deserve attention. Loosen one gate at a time in <code>daily_scan.py</code>: drop <code>ELITE_RS_PERCENTILE_MIN</code> to 80, or <code>ELITE_MOMENTUM_PASSES_MIN</code> to 3. If too loose, tighten them. Watch the Funnel section — "Elite qualified" counts tell you how much headroom the filter has.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>How Supertrend Longs is built and scored</summary>
    <div class="method-body">
      <p>The Supertrend-long section surfaces tickers where a <strong>fresh</strong> long flip has fired on the daily chart within the last <code>SUPERTREND_MAX_FLIP_AGE_DAYS</code> trading days (default 20). Supertrend is a trailing-stop indicator: when price is above the line, the trend is long and the line itself is your exit level. Uses the same parameters as the Positional Trading Tool: <strong>ATR period 10, multiplier 2.5</strong> (matches TradingView free tier).</p>
      <p><strong>Why the flip-age gate matters:</strong> without it, every sustained long trend keeps appearing day after day. The point of this section is "new signals I didn't see yesterday," not "every stock currently in a trend." Stale but still-strong trends live in the Recent Quality Supertrend history section instead.</p>
      <p>A ticker enters the pool when (a) it passed trend + behavioral + momentum confluence gates in Pass 1, (b) Supertrend direction is currently long, and (c) flip age ≤ 20 days. Same RS + sector gates apply as for breakouts and watchlist.</p>
      <p><strong>Supertrend score (0 to ~122):</strong></p>
      <table class="method-table">
        <thead><tr><th>Component</th><th class="num">Points</th></tr></thead>
        <tbody>
          <tr><td>Flip recency (bars since direction change)</td><td class="num mono">+30 if today, +25 if 1-3d, +15 if 4-7d, +5 if 8-15d</td></tr>
          <tr><td>RS strength (percentile vs eligible pool)</td><td class="num mono">rs_percentile ÷ 2, up to +50</td></tr>
          <tr><td>Momentum confluence passes</td><td class="num mono">+5 per check, up to +20</td></tr>
          <tr><td>Sector strength bonus</td><td class="num mono">+2 per sector rank above 7, up to +12</td></tr>
          <tr><td>Accumulation days (last 25 sessions)</td><td class="num mono">+1 per day, up to +10</td></tr>
        </tbody>
      </table>
      <p><strong>How to read the row:</strong></p>
      <ul>
        <li><strong>Flip Age</strong> — bars since the long signal fired. 0d = flipped today, 1-3d = fresh entry zone, &gt; 15d = mature trend (good for riding, worse for entry)</li>
        <li><strong>Current</strong> — today's close</li>
        <li><strong>ST Stop</strong> — the Supertrend trailing-stop line. Exit if price closes below this.</li>
        <li><strong>% Above Stop</strong> — how far current price sits above the stop. Smaller = tighter risk, bigger = more room to breathe but also more at risk if stop is hit</li>
      </ul>
      <p><strong>Why this complements breakouts and watchlist:</strong></p>
      <ul>
        <li>Breakouts = specific chart pattern just fired (point-in-time trigger)</li>
        <li>Watchlist = quality setup building, waiting for trigger (pre-trigger)</li>
        <li>Supertrend = already in a trend, trailing-stop managed (continuation)</li>
      </ul>
      <p>A ticker appearing in multiple sections (e.g., both Breakouts and Supertrend) is confluence — multiple signal types confirming the same name. Those are often the best setups.</p>
      <p><strong>Recent Quality Supertrend (history)</strong> aggregates the past 7 days (rolling week) of Supertrend-long entries. Only tickers whose peak Supertrend score ever hit 70+ in that window are eligible. Keep score adds recency, repeat appearances, and accumulation bonuses.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>Liquidity levels and the Positional (quality at a fair price) section</summary>
    <div class="method-body">
      <p><strong>Liquidity line under each ticker.</strong> Tier from the 20-session average dollar volume: Very high ≥ $100M/day, High ≥ $25M, Adequate ≥ $10M (the minimum to appear at all). Then average shares/day, average dollar volume/day, and <strong>1% of ADV</strong>: keeping your position below about 1% of a stock's average daily dollar volume means you can get in and out without moving the price, even on a fast exit. Hover the line for the full sentence.</p>
      <p><strong>Positional candidates</strong> come from the quality base (liquid, no crash gaps, above a rising 200 SMA) and must pass three groups of hard gates, then get scored.</p>
      <table class="method-table">
        <thead><tr><th>Group</th><th>Hard gates</th><th>Score (points)</th></tr></thead>
        <tbody>
          <tr><td>Financial quality</td><td>ROE ≥ 10%, net margin &gt; 0, free cash flow &gt; 0, debt/equity ≤ 2.0×</td><td>ROE 4–12, margin 2–10, revenue growth 0–10, debt 2–8, positive FCF 10 (max 50)</td></tr>
          <tr><td>Fair valuation</td><td>Forward P/E &gt; 0; PEG ≤ 2.0, or forward P/E ≤ 30 when PEG is missing</td><td>PEG 5–15 (or forward P/E 0–10), FCF yield 0–10, forward P/E below trailing +5 (max 30). Label: Undervalued if PEG ≤ 1 (or forward P/E ≤ 15), else Fair</td></tr>
          <tr><td>Not overextended</td><td>0–15% above 200 SMA, ≤ 8% above 50 SMA, daily RSI ≤ 65, weekly RSI ≤ 70</td><td>Closeness to 200 SMA 3–10, RSI 40–55 sweet spot 10 (max 20)</td></tr>
          <tr><td>Context</td><td>RS percentile ≥ 40</td><td>RS ÷ 5 (max 20), sector strength (max 12)</td></tr>
        </tbody>
      </table>
      <p><strong>Data source and caveats.</strong> Fundamentals come from Yahoo Finance via yfinance, cached in <code>data/fundamentals_cache.json</code> and refreshed weekly, at most 120 tickers per run (failed lookups retry after 3 days). The section fills in over the first few runs. Yahoo's figures can be stale, restated or missing; treat this as a shortlist and verify valuation in the filings before committing capital. A low PEG can also reflect a growth forecast that will not materialise.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>Fake-breakout detection, high-probability retests, liquidity filter, multi-timeframe RSI</summary>
    <div class="method-body">
      <p><strong>Liquidity filter (all sections).</strong> Before any pipeline runs, a ticker needs a price ≥ $10, a 20-session average volume ≥ 500K shares and average dollar volume ≥ $10M. Thin names produce unreliable breakouts, wide spreads and slippage. The funnel shows how many were dropped.</p>
      <p><strong>Fakeout risk badge.</strong> Every breakout is checked for warning signs. 0 flags = <span class="tag pos">Clean</span>, 1 = <span class="tag warn">Caution</span>, 2+ = <span class="tag neg">High risk</span> (hover or read the small text for the reasons).</p>
      <table class="method-table">
        <thead><tr><th>Flag</th><th>Meaning</th><th>Applies to</th></tr></thead>
        <tbody>
          <tr><td>Weak close / upper wick</td><td>Breakout day closed in the bottom half of its range: sellers rejected the move</td><td>Today + recent</td></tr>
          <tr><td>Marginal volume</td><td>Breakout volume under 2× average: little institutional commitment</td><td>Today + recent</td></tr>
          <tr><td>Extended &gt; 5% above level</td><td>Bought far above the pivot: poor risk/reward, prone to snap back</td><td>Today</td></tr>
          <tr><td>Gap-and-fade</td><td>Opened above the level, closed below the open</td><td>Today</td></tr>
          <tr><td>Adverse market regime</td><td>Weekly breadth &lt; 4: breakouts fail more often in weak tapes</td><td>Today</td></tr>
          <tr><td>No follow-through</td><td>Never got 3% above the level after breaking out</td><td>Recent</td></tr>
          <tr><td>Heavy selling since</td><td>A down day after the breakout traded more volume than the breakout day</td><td>Recent</td></tr>
          <tr><td>Back below level</td><td>Today's close is under the breakout level</td><td>Recent</td></tr>
        </tbody>
      </table>
      <p>Retest and Holding rows lose 5 score points per flag. Breakouts that close back below the level move to <strong>Fake / Failed Breakouts</strong> (Failing = below by &lt; 3%, Failed = below by &gt; 3%).</p>
      <p><strong><span class="tag hp">★ High probability</span> retest</strong> requires all of: the breakout level was an <em>old resistance</em> with ≥ 2 swing highs within 1.5% of it in the 120 sessions before the break; price broke it on volume, pulled back and is now retesting it as support; it closed up today (bounce); and it carries zero fakeout flags. These get +15 score, a gold row highlight, their own subsection, and the same highlight in Near Support when the support level is that broken resistance.</p>
      <p><strong>Multi-Timeframe RSI Momentum.</strong> RSI(14) on monthly and weekly closes both ≥ 60 (higher-timeframe trend strong), and daily RSI crossed from below 50 to ≥ 50 within the last 3 sessions, with volume on the cross day ≥ 1.0× its 20-session average. Gates: liquidity, behavioral, RS ≥ 60, sector ≤ 7. Score: monthly and weekly RSI above 60 (up to 15 each), cross freshness (today 20, 1d 15, 2d 10), cross-day volume (5–15), daily dip depth (≤ 40 +10, ≤ 45 +5), RS ÷ 2, sector, accumulation days. Price history is 3 years so monthly RSI has enough bars.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>How Support &amp; Resistance, Break &amp; Retest, and Reversal sections work</summary>
    <div class="method-body">
      <p><strong>Shared quality base.</strong> These three sections scan every ticker, not just main trend-filter survivors, because their setups are often mid-pullback. Each ticker must still pass: no −10% gap-down in 20 sessions, and close above a 200 SMA that is higher than 20 sessions ago. Each section then applies its own RS and sector gates, a minimum score, and a display cap, so only the technically strongest names show.</p>

      <p><strong>Support &amp; Resistance levels.</strong> Swing highs and lows (5 bars each side) from the last 120 sessions are clustered: pivots within 1.5% merge into one horizontal level. A level needs ≥ 2 touches. Old highs and old lows are pooled, so a former ceiling can show up as today's floor (role reversal). "Near" = within 3%.</p>
      <table class="method-table">
        <thead><tr><th>Score component</th><th>Near Support</th><th>Near Resistance</th></tr></thead>
        <tbody>
          <tr><td>Closeness to level (≤ 1% / ≤ 2% / ≤ 3%)</td><td class="mono">20 / 15 / 10</td><td class="mono">20 / 15 / 10</td></tr>
          <tr><td>Touches (4 each, max 5)</td><td class="mono">up to 20</td><td class="mono">up to 20</td></tr>
          <tr><td>RS percentile ÷ 2</td><td class="mono">up to 50</td><td class="mono">up to 50</td></tr>
          <tr><td>Sector strength</td><td class="mono">up to 12</td><td class="mono">up to 12</td></tr>
          <tr><td>Volume dry-up (5d avg &lt; 80% of prior 20d)</td><td class="mono">+10</td><td class="mono">+10</td></tr>
          <tr><td>Level within 2% of 50 SMA</td><td class="mono">+10</td><td class="mono">—</td></tr>
          <tr><td>Momentum passes × 5 / accumulation days</td><td class="mono">—</td><td class="mono">up to 20 / up to 10</td></tr>
          <tr><td>Gates</td><td class="mono">RS ≥ 60, sector ≤ 6</td><td class="mono">RS ≥ 70, sector ≤ 6</td></tr>
        </tbody>
      </table>

      <p><strong>Break &amp; Retest.</strong> Finds the most recent close above the prior 55-session high on ≥ 1.5× volume, 1–20 sessions ago (same-day breakouts are in Today's Breakouts). It is a <em>retest</em> when price has pulled back ≥ 3% from its post-breakout high, a low in the last 3 sessions came within 2% of the breakout level, and today's close is still at or above the level. Otherwise it is <em>holding above</em>. A close more than 3% below the level marks a failed breakout, which is dropped. Score: retest 25 (holding 10), bounce today +10, breakout volume above 1.5× up to +15, freshness up to +10, extended &gt; 10% −10, plus RS ÷ 2, momentum × 5, sector. Gates: RS ≥ 70, sector ≤ 6.</p>

      <p><strong>Reversal Swing.</strong> A pullback inside an intact uptrend: down 5–25% from the 20-day high, RSI(14) at or below 40 within the last 5 sessions, and today's candle is a bullish engulfing, an outside reversal (undercut prior low, closed above prior high), or a hammer (lower wick ≥ 2× body, close in top third). Score: trigger 15–20, pullback depth in the 8–15% sweet spot +15, RSI rebound ≥ 5 points +10, pullback low within 2% of the 50 SMA +10, today's volume ≥ 1.2× average +10, plus RS ÷ 2 and sector. Gates: RS ≥ 55, sector ≤ 7. Entry = today's close, stop = 1% under the 5-day low, TP1 = 2R; the prior 20-day high is the natural target.</p>

      <p><strong>How these differ from existing sections:</strong> Watchlist triggers are simple 20/55-day highs; Near Resistance uses multi-touch horizontal levels. Recovery is a 20/200 EMA turnaround from a downtrend; Reversal Swing is a short pullback inside an existing uptrend. These sections are recomputed from price history each day and are not archived.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>How Recovery Setups are built and scored</summary>
    <div class="method-body">
      <p>Recovery surfaces stocks "coming out of correction" — the 20 EMA has recently crossed above the 200 EMA from below and the 20 EMA is still close to the 200 EMA (not yet extended). These are classic turnaround setups: a stock went through a correction, found a bottom, and is now rebuilding its uptrend.</p>
      <p><strong>Entry conditions (all must hold):</strong></p>
      <ul>
        <li>20 EMA currently above 200 EMA</li>
        <li>20 EMA within 10% above 200 EMA (not yet extended)</li>
        <li>Crossover from below happened within the last 30 trading days</li>
        <li>20 EMA is rising (compared to 5 bars ago)</li>
        <li>No -10% gap-down in last 20 sessions (behavioral filter)</li>
        <li>Momentum confluence ≥ 3 of 4</li>
      </ul>
      <p><strong>Looser gates than other sections:</strong> Recovery accepts <strong>RS ≥ 60</strong> (not 85) and <strong>sector top 7</strong> (not 4). Why: a stock that just emerged from a correction has not yet rebuilt its relative strength — if we required RS ≥ 85, we'd never catch the turnaround at the inflection point, only after it had already run.</p>
      <p><strong>Recovery score (0 to ~142):</strong></p>
      <table class="method-table">
        <thead><tr><th>Component</th><th class="num">Points</th></tr></thead>
        <tbody>
          <tr><td>Freshness (days since cross)</td><td class="num mono">+30 if ≤ 5d, +25 if ≤ 10d, +15 if ≤ 20d, +5 if ≤ 30d</td></tr>
          <tr><td>Closeness (gap between EMAs)</td><td class="num mono">+20 if ≤ 3%, +15 if ≤ 5%, +10 if ≤ 7%, +5 if ≤ 10%</td></tr>
          <tr><td>RS strength</td><td class="num mono">rs_percentile ÷ 2, up to +50</td></tr>
          <tr><td>Momentum confluence passes</td><td class="num mono">+5 per check, up to +20</td></tr>
          <tr><td>Sector strength bonus</td><td class="num mono">+2 per rank above 7, up to +12</td></tr>
          <tr><td>Accumulation days</td><td class="num mono">+1 per day, up to +10</td></tr>
        </tbody>
      </table>
      <p><strong>How to read the row:</strong></p>
      <ul>
        <li><strong>Cross Age</strong> — days since 20 EMA crossed 200 EMA. Smaller = fresher = better. Highlighted green if ≤ 5 days.</li>
        <li><strong>EMA Gap</strong> — how far 20 EMA sits above 200 EMA. Smaller = closer to inflection point = better. Highlighted green if ≤ 3%.</li>
        <li><strong>Trade entry mechanics:</strong> look for the first pullback into the 20 EMA, or wait for a close above the recent swing high. Stop below the 200 EMA (or below recent swing low). Target: measured move from the correction depth, or trail with the 20 EMA.</li>
      </ul>
      <p><strong>Why this fills a gap:</strong> Breakouts and Supertrend both require strength (recent highs, trending long). Recovery catches names BEFORE they get strong — the turnaround phase. These setups can have outsized reward if the recovery continues, but have higher failure rates than confirmed breakouts, so size smaller.</p>
    </div>
  </details>

  <details class="method-block">
    <summary>How the Swing-Ready Watchlist is built and scored</summary>
    <div class="method-body">
      <p>The watchlist surfaces stocks that passed every quality gate (trend, behavioral, momentum confluence, RS percentile, sector regime) but <em>didn't</em> trigger any breakout pattern today. These are "stalking list" setups — quality candidates waiting for the trigger. Entering on the trigger (via buy-stop or alert) often gives better R:R than chasing a breakout already in motion.</p>
      <p><strong>Watchlist score (0 to ~112):</strong></p>
      <table class="method-table">
        <thead><tr><th>Component</th><th class="num">Points</th></tr></thead>
        <tbody>
          <tr><td>RS strength (percentile vs eligible pool)</td><td class="num mono">rs_percentile ÷ 2, up to +50</td></tr>
          <tr><td>Momentum confluence passes</td><td class="num mono">+5 per check (RSI, ADX, Weekly MACD, 52W pos), up to +20</td></tr>
          <tr><td>Sector strength bonus</td><td class="num mono">+2 per sector rank above 7, up to +12</td></tr>
          <tr><td>Accumulation days (IBD-style, last 25 sessions)</td><td class="num mono">+2 per day, cap at +20</td></tr>
          <tr><td>52W range position bonus</td><td class="num mono">+10 if in top 25% of 52W range</td></tr>
        </tbody>
      </table>
      <p><strong>Pending Trigger / Stop / TPs:</strong> the Trigger is the nearest resistance (20-day high; 55-day as fallback). Stop and TPs are computed from the trigger using the same logic as a fired breakout (stop = tighter of 7% below trigger or 20-day swing low; TP1 = 2R, TP2 = 3R). These are inactive until price actually breaks the Trigger — set alerts and let the setup come to you.</p>
      <p><strong>Recent Quality Watchlist (history)</strong> aggregates the past 7 days (rolling week) of watchlist entries. Only tickers whose peak watchlist score ever hit 70+ in that window are eligible. Composite ranking (keep score) adds bonuses for recency, repeat appearances, and accumulation.</p>
      <p><strong>What to look for:</strong></p>
      <ul>
        <li><strong>% to Go</strong> close to 0 (e.g., &lt; 3%): the trigger is imminent — prime alert candidate</li>
        <li><strong>AccDays ≥ 7:</strong> clear institutional accumulation under the surface</li>
        <li><strong>Repeat appearances</strong> on the history view: setup has been building for weeks</li>
      </ul>
    </div>
  </details>
</section>
"""


# ============================================================================
# Top-level renderer
# ============================================================================

# Category colours (one per strategy family)
PANEL_COLORS = {
    "breakout": "#2A6FDB", "watch": "#138A8A", "retest": "#C8961E", "trend": "#7B4FBF",
    "pullback": "#2E7D5B", "recovery": "#D9731A", "positional": "#1F3A5F", "diag": "#6B6B75",
}

CATEGORY_GUIDE = {
    "breakout": (
        "Stocks clearing a 20/55/252-day high, horizontal resistance or a volatility contraction today on ≥ 1.5× volume, "
        "with top-15% relative strength, 4/4 momentum and a strong sector.",
        "Enter near the close or next session if price holds above the breakout level. Skip High fakeout risk rows or "
        "anything > 5% above the level. Use the shown stop; take partial profits at TP1 (2R)."),
    "watch": (
        "Quality names coiling just under a trigger (20/55-day high) or under a horizontal resistance tested ≥ 2 times. "
        "Not actionable yet.",
        "Set price alerts at the trigger/level. Act only on a daily close above it with ≥ 1.5× volume; the pending stop "
        "and target apply from that moment. Tightening volume under the level is a plus."),
    "retest": (
        "Recent breakouts (last 20 sessions): pullbacks to the old breakout level (the lowest-risk entry), names still "
        "holding above, and failed breakouts. ★ = old resistance tested ≥ 2× now holding as support, bounced today.",
        "Prefer ★ and 'Bounce today' rows; stop just under the retest low. Holders > 10% extended: wait for a retest. "
        "Never buy from the Avoid list; if you hold one, the breakout thesis is broken."),
    "trend": (
        "Fresh daily Supertrend (ATR 10 × 2.5) long flips in strong names. The Supertrend line itself is the trailing stop. "
        "Same settings as the Positional Trading Tool.",
        "Best entries within ~3 days of the flip. Move the stop up to the Supertrend line each day and exit on a daily "
        "close below it. Older flips are for riding, not for new entries."),
    "pullback": (
        "Buying dips inside uptrends: price resting on tested support, bullish reversal candles after a 5–25% pullback, "
        "and RSI resets (monthly & weekly RSI > 60, daily RSI back above 50).",
        "Wait for confirmation (bounce candle or close above the prior day's high). Keep stops tight under the level or "
        "the 5-day low. Short-term counter-trend, so size smaller than breakouts."),
    "recovery": (
        "Stocks coming out of a correction: the 20 EMA just crossed above the 200 EMA and is still within 10% of it. "
        "Looser RS gates, because relative strength is still rebuilding.",
        "Higher reward, higher failure rate. Enter on the first pullback to the 20 EMA or a close above the recent swing "
        "high; stop below the 200 EMA. Size small."),
    "positional": (
        "Profitable, cash-generative, moderately levered companies at PEG ≤ 2, in a long-term uptrend but not stretched "
        "(≤ 15% above the 200 SMA, RSI ≤ 65). Fundamentals from Yahoo, refreshed weekly.",
        "Weeks-to-months holds. Build in tranches near the 50 SMA add zone; stop 3% under the 200 SMA. Verify the numbers "
        "in the company's filings before committing capital."),
}


def _sc(r: dict) -> float:
    for k in ("score", "watchlist_score", "supertrend_score", "recovery_score", "best_score"):
        if r.get(k) is not None:
            return float(r[k])
    return 0.0


# (setup label, entry key, stop key, target key) per today-table kind
_TODAY_FIELDS = {
    "breakout":   ("Breakout",        "entry",   "stop",             "tp1"),
    "watchlist":  ("Trigger",         "trigger", "stop_pending",     "tp1_pending"),
    "resistance": ("Resistance",      "level",   "support_below",    None),
    "high_prob":  ("★ Retest",        "close",   "stop",             "tp1"),
    "retest":     ("Retest",          "close",   "stop",             "tp1"),
    "holding":    ("Holding",         "close",   "breakout_level",   None),
    "supertrend": ("ST flip",         "close",   "supertrend_level", None),
    "support":    ("Support",         "close",   "stop",             "target"),
    "reversal":   ("Reversal",        "entry",   "stop",             "tp1"),
    "mtf_rsi":    ("RSI reset",       "entry",   "stop",             "tp1"),
    "recovery":   ("Recovery",        "close",   "long_ema",         None),
    "positional": ("Positional",      "close",   "stop",             "target"),
}
# (label, level key) per weekly-list kind
_WEEK_FIELDS = {
    "breakout":   ("Breakout",   "peak_entry"),
    "watchlist":  ("Trigger",    "peak_trigger"),
    "supertrend": ("ST flip",    "peak_close"),
    "recovery":   ("Recovery",   "peak_close"),
}


def _mini_today(items: list[tuple[str, dict]], cap: int = 10) -> str:
    if not items:
        return '<div class="more">Nothing today.</div>'
    items = sorted(items, key=lambda kv: _sc(kv[1]), reverse=True)
    rows = []
    for kind, r in items[:cap]:
        label, ek, sk, tk = _TODAY_FIELDS[kind]
        tr_cls = ' class="hp"' if r.get("high_probability") else ""
        rows.append(
            f'<tr{tr_cls}><td class="tk">{_tk(r, compact=True)}</td><td><span class="setup">{label}</span></td>'
            f'<td class="num mono">{_sc(r):.0f}</td><td class="num mono">{_fmt(r.get(ek), ".2f")}</td>'
            f'<td class="num mono">{_fmt(r.get(sk), ".2f")}</td>'
            f'<td class="num mono">{_fmt(r.get(tk), ".2f") if tk else "—"}</td></tr>')
    more = f'<div class="more">+{len(items) - cap} more in Full detail</div>' if len(items) > cap else ""
    return ('<table class="mini"><thead><tr><th>Ticker</th><th>Setup</th><th class="num">Score</th>'
            '<th class="num">Entry</th><th class="num">Stop</th><th class="num">Target</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>{more}')


def _mini_week(items: list[tuple[str, dict]], today_str: str, cap: int = 8) -> str:
    if not items:
        return '<div class="more">No names have reached the quality bar this week yet.</div>'
    items = sorted(items, key=lambda kv: kv[1].get("keep_score", _sc(kv[1])), reverse=True)
    rows = []
    for kind, r in items[:cap]:
        if kind == "setup":
            label, level = _SETUP_LABELS.get(r["setup"], r["setup"]), r.get("level")
        else:
            label, lk = _WEEK_FIELDS[kind]
            level = r.get(lk)
        tr_cls = ' class="hp"' if r.get("high_probability") else ""
        pick = r.get("best_score_date", "")
        pick_html = f'<span class="streak">today</span>' if pick == today_str else escape(pick[5:])
        rows.append(
            f'<tr{tr_cls}><td class="tk">{_tk(r, compact=True)}</td><td><span class="setup">{escape(label)}</span></td>'
            f'<td class="num mono">{_sc(r):.0f}</td><td class="num mono">×{r.get("appearances", 1)}</td>'
            f'<td class="num mono">{pick_html}</td><td class="num mono">{_fmt(level, ".2f")}</td></tr>')
    more = f'<div class="more">+{len(items) - cap} more in Full detail</div>' if len(items) > cap else ""
    return ('<table class="mini"><thead><tr><th>Ticker</th><th>Setup</th><th class="num">Best</th>'
            '<th class="num">Seen</th><th class="num">Picked</th><th class="num">Level</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>{more}')


def _category(cid: str, title: str, today_items: list, week_items: list, detail_html: str,
              today_str: str, avoid: list[dict] | None = None) -> str:
    summary, how = CATEGORY_GUIDE[cid]
    avoid_html = ""
    if avoid:
        avoid_html = ('<div class="avoid"><b>Avoid (failed breakouts):</b> '
                      + ", ".join(escape(a["ticker"]) for a in avoid) + "</div>")
    return f"""
<section class="cat" id="p-{cid}" style="--pc:{PANEL_COLORS[cid]}">
  <div class="cat-head"><span class="c-title">{title}</span>
    <span class="c-counts">today {len(today_items)} · this week {len(week_items)}</span></div>
  <div class="cat-grid">
    <div class="cat-guide"><h4>What it is</h4><p>{escape(summary)}</p><h4>How to use it</h4><p>{escape(how)}</p></div>
    <div class="cat-col today"><h4>Today <span class="n">{len(today_items)}</span></h4>{_mini_today(today_items)}{avoid_html}</div>
    <div class="cat-col week"><h4>This week's quality list <span class="n">{len(week_items)}</span></h4>{_mini_week(week_items, today_str)}</div>
  </div>
  <details class="detail"><summary>Full detail tables</summary><div class="detail-body">{detail_html}</div></details>
</section>"""


def _sub(title: str, note: str = "") -> str:
    note_html = f' <span class="count">· {note}</span>' if note else ""
    return f'<h3 class="subsection">{title}{note_html}</h3>'


def _history(label: str, n: int, table: str) -> str:
    return f'<h3 class="subsection">{label} <span class="count">· {n}</span></h3>{table}'


def render(
    *,
    date_str: str,
    generated_at_utc: str,
    breadth: dict,
    candidates: list[dict],
    watchlist: list[dict] | None = None,
    supertrend: list[dict] | None = None,
    recovery: list[dict] | None = None,
    support: list[dict] | None = None,
    resistance: list[dict] | None = None,
    retest: list[dict] | None = None,
    holding: list[dict] | None = None,
    reversal: list[dict] | None = None,
    fake: list[dict] | None = None,
    high_prob: list[dict] | None = None,
    mtf_rsi: list[dict] | None = None,
    positional: list[dict] | None = None,
    recent_quality: list[dict],
    recent_quality_watchlist: list[dict] | None = None,
    recent_quality_supertrend: list[dict] | None = None,
    recent_quality_recovery: list[dict] | None = None,
    recent_resistance: list[dict] | None = None,
    recent_retest: list[dict] | None = None,
    recent_pullback: list[dict] | None = None,
    recent_positional: list[dict] | None = None,
    sector_counts: dict,
    funnel: dict,
    eligible_refreshed_at: str,
) -> str:
    """Assemble the dashboard: one colour-coded block per strategy category."""
    L = lambda x: x or []
    watchlist, supertrend, recovery = L(watchlist), L(supertrend), L(recovery)
    support, resistance, retest, holding = L(support), L(resistance), L(retest), L(holding)
    reversal, fake, high_prob, mtf_rsi, positional = L(reversal), L(fake), L(high_prob), L(mtf_rsi), L(positional)
    rq, rq_wl, rq_st, rq_rec = L(recent_quality), L(recent_quality_watchlist), L(recent_quality_supertrend), L(recent_quality_recovery)
    rq_res, rq_ret, rq_pb, rq_pos = L(recent_resistance), L(recent_retest), L(recent_pullback), L(recent_positional)
    f = funnel

    # ---- Confluence: tickers in 2+ sections TODAY (fake = avoid list and ★ = subset of retest: excluded) ----
    section_rows = {
        "Breakouts": candidates, "Watchlist": watchlist, "Near resistance": resistance,
        "Break & retest": retest, "Holding above": holding, "Supertrend": supertrend,
        "Near support": support, "Reversal": reversal, "MTF RSI": mtf_rsi,
        "Recovery": recovery, "Positional": positional,
    }
    sections_by_ticker: dict[str, set] = {}
    for name, rows in section_rows.items():
        for r in rows:
            sections_by_ticker.setdefault(r["ticker"], set()).add(name)
    for rows in list(section_rows.values()) + [high_prob, fake, rq, rq_wl, rq_st, rq_rec, rq_res, rq_ret, rq_pb, rq_pos]:
        for r in rows:
            r["confluence"] = sorted(sections_by_ticker.get(r["ticker"], ()))
    multi = sorted(((t, sorted(sec)) for t, sec in sections_by_ticker.items() if len(sec) >= 2),
                   key=lambda kv: -len(kv[1]))

    cats = [
        ("breakout", "Breakouts",
         [("breakout", r) for r in candidates],
         [("breakout", r) for r in rq],
         _sub("Today's breakouts", f"top {f.get('max_breakouts_cap', 5)}") + _render_candidates_table(candidates)
         + _history("This week's quality breakouts", len(rq), _render_recent_quality_table(rq, date_str)), None),
        ("watch", "Pre-breakout watch",
         [("watchlist", r) for r in watchlist] + [("resistance", r) for r in resistance],
         [("watchlist", r) for r in rq_wl] + [("setup", r) for r in rq_res],
         _sub("Swing-ready watchlist", f"top {f.get('max_watchlist_cap', 8)}") + _render_watchlist_table(watchlist)
         + _sub("Near resistance", f"top {f.get('max_resistance_cap', 10)}") + _render_resistance_table(resistance)
         + _history("This week's quality watchlist", len(rq_wl), _render_recent_quality_watchlist_table(rq_wl, date_str))
         + _history("This week's quality near-resistance names", len(rq_res), _render_setup_history_table(rq_res, date_str)), None),
        ("retest", "Break &amp; retest",
         [("high_prob" if r.get("high_probability") else "retest", r) for r in retest] + [("holding", r) for r in holding],
         [("setup", r) for r in rq_ret],
         _sub('<span class="tag hp">★</span> High-probability: old resistance retested as support') + _render_high_prob_table(high_prob)
         + _sub("Break &amp; retest", f"top {f.get('max_retest_cap', 8)}") + _render_retest_table(retest)
         + _sub("Holding above breakout", f"top {f.get('max_holding_cap', 8)}") + _render_holding_table(holding)
         + _sub("Fake / failed breakouts", "avoid list") + _render_fake_table(fake)
         + _history("This week's quality breakouts-in-progress", len(rq_ret), _render_setup_history_table(rq_ret, date_str)), fake),
        ("trend", "Trend following: Supertrend flips",
         [("supertrend", r) for r in supertrend],
         [("supertrend", r) for r in rq_st],
         _sub("Today's Supertrend longs", f"fresh flips ≤ {f.get('supertrend_max_flip_age_days', 20)}d") + _render_supertrend_table(supertrend)
         + _history("This week's quality Supertrend names", len(rq_st), _render_recent_quality_supertrend_table(rq_st, date_str)), None),
        ("pullback", "Pullback &amp; reversal",
         [("support", r) for r in support] + [("reversal", r) for r in reversal] + [("mtf_rsi", r) for r in mtf_rsi],
         [("setup", r) for r in rq_pb],
         _sub("Near support", f"top {f.get('max_support_cap', 10)}") + _render_support_table(support)
         + _sub("Reversal swing setups", f"top {f.get('max_reversal_cap', 6)}") + _render_reversal_table(reversal)
         + _sub("Multi-timeframe RSI momentum") + _render_mtf_rsi_table(mtf_rsi)
         + _history("This week's quality pullback names", len(rq_pb), _render_setup_history_table(rq_pb, date_str)), None),
        ("recovery", "Recovery: coming out of correction",
         [("recovery", r) for r in recovery],
         [("recovery", r) for r in rq_rec],
         _sub("Today's recovery setups", f"top {f.get('max_recovery_cap', 6)}") + _render_recovery_table(recovery)
         + _history("This week's quality recovery names", len(rq_rec), _render_recent_quality_recovery_table(rq_rec, date_str)), None),
        ("positional", "Positional: quality at a fair price",
         [("positional", r) for r in positional],
         [("setup", r) for r in rq_pos],
         _sub("Today's positional candidates", f"top {f.get('max_positional_cap', 8)}") + _render_positional_table(positional)
         + _history("This week's quality positional names", len(rq_pos), _render_setup_history_table(rq_pos, date_str)), None),
    ]

    def top_names(items):
        names = [r["ticker"] for _, r in sorted(items, key=lambda kv: _sc(kv[1]), reverse=True)]
        return ", ".join(dict.fromkeys(names)) or "—"

    glance = "".join(
        f'<a href="#p-{cid}" style="--pc:{PANEL_COLORS[cid]}"><div class="g-title">{title}</div>'
        f'<div class="g-count{" zero" if not today else ""}">{len(today)}</div>'
        f'<div class="g-sub">today · {len(week)} this week</div>'
        f'<div class="g-top" title="{escape(top_names(today))}">{escape(top_names(today))}</div></a>'
        for cid, title, today, week, _d, _a in cats
    )
    multi_html = (
        "".join(f'<span class="cf {"cf3" if len(sec) >= 3 else "cf2"}" title="{escape(", ".join(sec))}">'
                f'{escape(t)} ×{len(sec)}</span> ' for t, sec in multi)
        if multi else '<span class="dim">none today</span>'
    )
    cats_html = "".join(_category(cid, title, today, week, detail, date_str, avoid)
                        for cid, title, today, week, detail, avoid in cats)
    diag_body = f"""
  <div class="secondary">
    <div><h3 class="subsection">Sector distribution</h3>{_render_sector_breakdown(sector_counts)}</div>
    <div><h3 class="subsection">Funnel (where candidates drop out)</h3>{_render_funnel(funnel)}</div>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swing Scan — {escape(date_str)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">
  <header class="masthead">
    <div class="masthead-top">
      <div>
        <h1 class="title">Swing &amp; Positional Scan</h1>
        <div class="title-sub">Curated US universe, filtered for trend, momentum, volume, liquidity and value.</div>
      </div>
      <div class="date-block">
        <div class="date-primary">{escape(date_str)}</div>
        <div class="date-secondary">Generated {escape(generated_at_utc)}</div>
      </div>
    </div>
    {_render_breadth_panel(breadth)}
  </header>

  <h2 class="section">At a glance</h2>
  <div class="glance">{glance}</div>
  <div class="legend">
    <span><b>In several sections today:</b> {multi_html}</span>
  </div>
  <div class="legend">
    <span><span class="sw" style="background:#EFE3FF"></span>Row in 2 sections</span>
    <span><span class="sw" style="background:#FFDCEB"></span>Row in 3+ sections</span>
    <span><span class="sw" style="background:rgba(200,150,30,0.25)"></span>★ High-probability retest</span>
    <span><span class="ldot t-vh"></span>Very high liquidity ≥ $100M/day</span>
    <span><span class="ldot t-h"></span>High ≥ $25M</span>
    <span><span class="ldot t-a"></span>Adequate ≥ $10M</span>
    <span>Full liquidity levels (shares/day, $/day, 1% ADV) are in each block's Full detail tables.</span>
  </div>

  {cats_html}

  <details class="panel" id="p-diag" style="--pc:{PANEL_COLORS['diag']}">
    <summary><span class="p-title">Diagnostics</span><span class="p-desc">Sector distribution and the full filter funnel.</span></summary>
    <div class="panel-body">{diag_body}</div>
  </details>
  <details class="panel" id="p-method" style="--pc:{PANEL_COLORS['diag']}">
    <summary><span class="p-title">Methodology</span><span class="p-desc">How every score, gate and section works.</span></summary>
    <div class="panel-body">{_render_methodology()}</div>
  </details>

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


# ============================================================================
# Root index — landing page listing all reports
# ============================================================================

def render_index(reports_dir: Path, latest: dict | None = None) -> str:
    """Render root index.html. Lists every dated report (newest first).

    Args:
      reports_dir: folder containing YYYY-MM-DD.html files
      latest: dict with keys {date, weekly_breadth, monthly_breadth,
              signals, shown, top_ticker, top_score, eligible} for today's
              scan. If None, index shows history only.
    """
    # Discover all report files, newest first
    if reports_dir.exists():
        report_files = sorted(
            [p for p in reports_dir.glob("*.html") if p.stem != "index"],
            key=lambda p: p.stem,
            reverse=True,
        )
    else:
        report_files = []

    # Latest-scan panel (uses current scan data if provided, else parses filename)
    if latest is None and report_files:
        latest = {"date": report_files[0].stem}

    if latest is None:
        latest_panel = (
            '<section class="breadth"><div class="breadth-metric" '
            'style="grid-column: 1 / -1;"><div class="label">Status</div>'
            '<div class="value" style="font-size:16px;font-weight:400;'
            'margin-top:6px;">No reports generated yet. Wait for the next '
            'scheduled scan or trigger one manually.</div></div></section>'
        )
    else:
        verdict = verdict_from_score(latest.get("weekly_breadth", 5.0))
        vcolor = verdict_color(verdict)
        weekly = latest.get("weekly_breadth")
        monthly = latest.get("monthly_breadth")
        top_desc = "—"
        if latest.get("top_ticker") and latest.get("top_score") is not None:
            top_desc = f'{escape(latest["top_ticker"])} @ {latest["top_score"]:.0f}'

        breadth_line = ""
        if weekly is not None and monthly is not None:
            breadth_line = (
                f'<div class="breadth-metric">'
                f'<div class="label">Week / Month Breadth</div>'
                f'<div class="value mono">{weekly:.1f}'
                f'<span class="max"> / {monthly:.1f}</span></div></div>'
                f'<div class="breadth-verdict">'
                f'<div class="label">Environment</div>'
                f'<div style="margin-top:8px;">'
                f'<span class="verdict-tag" style="background:{vcolor}">'
                f'{escape(verdict)}</span></div></div>'
            )

        signals_line = ""
        if latest.get("signals") is not None:
            signals_line = (
                f'<p style="text-align:center;color:var(--muted);'
                f'font-size:13px;margin-top:16px;">'
                f'{latest["signals"]} breakout signals today, '
                f'{latest.get("shown", 0)} scored ≥ 40. '
                f'Top pick: <strong style="color:var(--ink)">{top_desc}</strong>.</p>'
            )

        latest_panel = f"""
<section class="breadth">
  <div class="breadth-metric">
    <div class="label">Latest Scan</div>
    <div class="value mono" style="font-size:22px;">{escape(latest["date"])}</div>
  </div>
  {breadth_line}
</section>
<div style="text-align:center;padding:20px 0 4px 0;">
  <a href="reports/{escape(latest["date"])}.html"
     style="display:inline-block;padding:10px 24px;background:var(--accent);
            color:var(--surface);text-decoration:none;font-weight:500;
            font-size:14px;letter-spacing:0.02em;">
    Open Latest Report →
  </a>
</div>
{signals_line}
"""

    # History list — all past reports
    if report_files:
        history_rows = "".join(
            f'<li><a href="reports/{escape(p.stem)}.html" class="mono">'
            f'{escape(p.stem)}</a></li>'
            for p in report_files
        )
        history_html = f"""
<h2 class="section">All Reports</h2>
<ul class="report-list">{history_rows}</ul>
<p style="color:var(--muted);font-size:12px;margin-top:12px;">
  {len(report_files)} report{"s" if len(report_files) != 1 else ""} archived.
</p>
"""
    else:
        history_html = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Breakout Swing Scan</title>
<style>{CSS}
.report-list {{ list-style: none; padding: 0; margin: 0;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px; }}
.report-list li a {{ display: block; padding: 8px 12px;
  border: 1px solid var(--rule); background: var(--surface);
  color: var(--ink); text-decoration: none; font-size: 13px;
  text-align: center; transition: background 0.15s; }}
.report-list li a:hover {{ background: rgba(42, 74, 107, 0.06);
  border-color: var(--accent); }}
</style>
</head>
<body>
<div class="container">
  <header class="masthead">
    <div class="masthead-top">
      <div>
        <h1 class="title">Breakout Swing Scan</h1>
        <div class="title-sub">Daily breakout candidates from a curated US universe. Runs Mon–Fri after US market close.</div>
      </div>
    </div>
    {latest_panel}
  </header>
  {history_html}
  <footer>
    <div>Reports refresh Mon–Fri at ~22:00 UTC.</div>
    <div>Not investment advice. For personal research use.</div>
  </footer>
</div>
</body>
</html>
"""


def write_index(html: str, output_path: Path = Path("index.html")) -> Path:
    output_path.write_text(html, encoding="utf-8")
    return output_path
