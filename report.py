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
  <td class="ticker">{escape(c["ticker"])}</td>
  <td class="{_score_class(c["score"])} num mono">{_fmt(c["score"], ".0f")}</td>
  <td class="patterns">{pattern_tags}</td>
  <td class="num mono">{_fmt(c["entry"], ".2f")}</td>
  <td class="num mono">{_fmt(c["stop"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp1"], ".2f")}</td>
  <td class="num mono">{_fmt(c["tp2"], ".2f")}</td>
  <td class="num mono">{_fmt(rr, ".1f")}R</td>
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
  <td class="ticker">{escape(c["ticker"])}</td>
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
  <td class="ticker">{escape(c["ticker"])}</td>
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
    """Historical quality watchlist — aggregated across the 90-day archive,
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
  <td class="ticker">{escape(c["ticker"])}</td>
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
    steps = [
        ("Eligible pool", funnel["eligible"]),
        ("Skipped (no data)", funnel.get("no_data", 0)),
        ("Passed trend filter", funnel["trend_pass"]),
        ("Passed behavioral filter", funnel["behavioral_pass"]),
        ("Passed momentum confluence", funnel.get("momentum_pass", 0)),
        ("— Pattern triggered (→ breakouts)", funnel.get("pattern_pass", funnel.get("signals", 0))),
        ("— No pattern yet (→ watchlist pool)", funnel.get("watchlist_raw", 0)),
        ("Dropped by RS gate (breakouts)", funnel.get("rs_gated", 0)),
        ("Dropped by sector gate (breakouts)", funnel.get("sector_gated", 0)),
        ("Final breakout signals (archived)", funnel["signals"]),
        ("Final watchlist entries (archived)", funnel.get("watchlist_signals", 0)),
        ("Elite breakouts qualified", funnel.get("elite_breakouts", 0)),
        ("Elite watchlist qualified", funnel.get("elite_watchlist", 0)),
        (f"Breakouts shown (top {bo_cap})", funnel["shown"]),
        (f"Watchlist shown (top {wl_cap})", funnel.get("watchlist_shown", 0)),
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
      <p>The Recent Quality Breakouts section aggregates every signal from the past 90 days, then picks the top 10 by a composite <strong>keep score</strong>:</p>
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
      <p><strong>What this fixes:</strong> too many names to review wasted time and encouraged skimming. 5 breakouts and 8 watchlist entries is small enough to study each one properly, understand its chart, and make a real trade/no-trade decision. Everything below elite still accrues in the 90-day archives — nothing is lost, just not surfaced for daily review.</p>
      <p><strong>If this feels too strict:</strong> on a strong market day, 8-10 names may deserve attention. Loosen one gate at a time in <code>daily_scan.py</code>: drop <code>ELITE_RS_PERCENTILE_MIN</code> to 80, or <code>ELITE_MOMENTUM_PASSES_MIN</code> to 3. If too loose, tighten them. Watch the Funnel section — "Elite qualified" counts tell you how much headroom the filter has.</p>
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
      <p><strong>Recent Quality Watchlist (history)</strong> aggregates the past 90 days of watchlist entries. Only tickers whose peak watchlist score ever hit 70+ are eligible. Composite ranking (keep score) adds bonuses for recency, repeat appearances, and accumulation.</p>
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

def render(
    *,
    date_str: str,
    generated_at_utc: str,
    breadth: dict,
    candidates: list[dict],
    watchlist: list[dict] | None = None,
    recent_quality: list[dict],
    recent_quality_watchlist: list[dict] | None = None,
    sector_counts: dict,
    funnel: dict,
    eligible_refreshed_at: str,
) -> str:
    """Assemble the full HTML report."""
    watchlist = watchlist or []
    recent_quality_watchlist = recent_quality_watchlist or []

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

  <h2 class="section">Today's Breakouts <span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted);font-size:11px;">(elite-filtered, top {funnel.get("max_breakouts_cap", 5)} max)</span></h2>
  {_render_candidates_table(candidates)}

  <h2 class="section">Today's Swing-Ready Watchlist <span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted);font-size:11px;">(elite-filtered, top {funnel.get("max_watchlist_cap", 8)} max)</span></h2>
  {_render_watchlist_table(watchlist)}

  <h2 class="section">Recent Quality Breakouts <span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted);font-size:11px;">(top 10 by conviction, appearances, volume, and recency)</span></h2>
  {_render_recent_quality_table(recent_quality, date_str)}

  <h2 class="section">Recent Quality Watchlist <span style="text-transform:none;letter-spacing:0;font-weight:400;color:var(--muted);font-size:11px;">(top 10 past watchlist entries by composite ranking)</span></h2>
  {_render_recent_quality_watchlist_table(recent_quality_watchlist, date_str)}

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
