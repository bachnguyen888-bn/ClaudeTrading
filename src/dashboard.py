"""
Dashboard: a terminal summary plus a self-contained HTML report.

The terminal summary uses plain ASCII so it works in any console (including
Windows). The HTML report needs no internet and no extra packages: open
results/<run_id>/report.html in your browser.
"""

from __future__ import annotations

import html
import json
import math
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .safety import BANNER

WIDTH = 66
SAMPLE_PRICES_NOTE = ("Sample data: outcomes are real BTC history but the market PRICES are simulated "
                      "(with random noise a model can exploit). Returns here say nothing about real markets.")


# --- formatting helpers ---------------------------------------------------

def pct(value: Optional[float], signed: bool = True) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def money(value: Optional[float], signed: bool = False) -> str:
    if value is None:
        return "n/a"
    sign = "+" if signed and value > 0 else ("-" if value < 0 else "")
    return f"{sign}${abs(value):,.2f}"


def num(value: Optional[float], decimals: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{decimals}f}"


def _line(char: str = "-") -> str:
    return char * WIDTH


def _row(label: str, *values: str) -> str:
    return f"  {label:<26}" + "".join(f"{v:>18}" for v in values)


# --- terminal ---------------------------------------------------------------

def ascii_chart(values: Sequence[float], width: int = 58, height: int = 10) -> List[str]:
    """Tiny line chart made of characters. Each column shows the value at the end of its slice."""
    if len(values) < 2:
        return []
    step = len(values) / width
    sampled = [values[min(len(values) - 1, int((c + 1) * step) - 1)] for c in range(min(width, len(values)))]
    lo, hi = min(sampled), max(sampled)
    span = (hi - lo) or 1.0
    grid = [[" "] * len(sampled) for _ in range(height)]
    for c, value in enumerate(sampled):
        r = height - 1 - int(round((value - lo) / span * (height - 1)))
        grid[r][c] = "*"
    lines = []
    for r, cells in enumerate(grid):
        label = money(hi) if r == 0 else (money(lo) if r == height - 1 else "")
        lines.append(f"  {label:>12} |" + "".join(cells))
    lines.append("  " + " " * 12 + " +" + "-" * len(sampled))
    return lines


def print_summary(payload: Dict[str, Any], equity_values: Optional[Sequence[float]] = None,
                  show_chart: bool = True) -> None:
    print(render_summary(payload, equity_values, show_chart))


def render_summary(payload: Dict[str, Any], equity_values: Optional[Sequence[float]] = None,
                   show_chart: bool = True) -> str:
    if payload.get("experiment") == "prediction_markets":
        lines = _prediction_lines(payload)
    else:
        lines = _backtest_lines(payload)
    if show_chart and equity_values:
        lines += ["", "  Account value over time", *ascii_chart(equity_values)]
    files = payload.get("files", {})
    if files:
        lines += ["", "  Files"]
        lines += [f"    {name:<14} {path}" for name, path in files.items()]
    lines += ["", "  Reminder: past results on one dataset do not predict future returns.", _line("=")]
    return "\n".join([BANNER] + lines)


def _backtest_lines(p: Dict[str, Any]) -> List[str]:
    m = p["metrics"]
    lines = [
        f"  BTC BACKTEST SUMMARY   run {p['run_id']}",
        _line(),
        f"  Strategy: {p.get('strategy', '?')}",
        f"  Data:     {p.get('data_label', '?')}",
        f"  Period:   {m['start_date']} -> {m['end_date']} ({m['years']} years, {m['bars']} bars)",
        "",
        _row("", "Strategy", "Buy & hold"),
        _row("Total return", pct(m["total_return_pct"]), pct(m["buy_hold_return_pct"])),
        _row("Max drawdown", pct(-m["max_drawdown_pct"]), pct(-m["buy_hold_max_drawdown_pct"])),
        _row("CAGR (yearly growth)", pct(m["cagr_pct"])),
        _row("Sharpe ratio", num(m["sharpe"])),
        _row("Start -> end equity", f"{money(m['start_equity'])} -> {money(m['end_equity'])}"),
        "",
        "  Trades",
        _row("Completed trades", str(m["trades"]), f"win rate {pct(m['win_rate_pct'], signed=False)}"),
        _row("Wins / losses", f"{m['wins']} / {m['losses']}", f"PF {num(m['profit_factor'])}"),
        _row("Average win / loss", money(m["avg_win"], True), money(m["avg_loss"], True)),
        _row("Largest win / loss", money(m["largest_win"], True), money(m["largest_loss"], True)),
        _row("Fees paid", money(m["total_fees"])),
        _row("Time in market", pct(m["exposure_pct"], signed=False)),
    ]
    if p.get("exit_reasons"):
        lines += ["", "  Why trades closed"]
        lines += [_row(reason, str(count)) for reason, count in sorted(p["exit_reasons"].items())]
    lines += _skip_lines(p, "Skipped signals")
    if p.get("halted"):
        lines += ["", "  !! Kill switch tripped: max_drawdown_pct reached; trading stopped."]
    return lines


def _prediction_lines(p: Dict[str, Any]) -> List[str]:
    m = p["metrics"]
    lines = [
        f"  PREDICTION-MARKET PAPER SUMMARY   run {p['run_id']}",
        _line(),
        f"  Data:     {p.get('data_label', '?')}",
        f"  Period:   {m['start_date']} -> {m['end_date']} ({m['markets']} markets)",
        "",
        _row("Total return", pct(m["total_return_pct"])),
        _row("Max drawdown", pct(-m["max_drawdown_pct"])),
        _row("Start -> end bankroll", f"{money(m['start_equity'])} -> {money(m['end_equity'])}"),
        _row("Bets placed", str(m["bets"]), f"win rate {pct(m['win_rate_pct'], signed=False)}"),
        _row("Wins / losses", f"{m['wins']} / {m['losses']}", f"PF {num(m['profit_factor'])}"),
        _row("Total staked / fees", money(m["total_staked"]), money(m["total_fees"])),
        _row("Average edge per bet", num(m["avg_edge"], 3)),
        "",
        "  Forecast quality (Brier score: lower is better, 0.25 = coin flip)",
        _row("Your model", num(m["brier_model"], 4)),
        _row("Market prices", num(m["brier_market"], 4)),
        _row("Markets scored", str(m["forecasts_scored"])),
    ]
    calibration = p.get("calibration") or []
    if calibration:
        lines += ["", "  Calibration: when we said X%, how often did YES happen?",
                  f"    {'bucket':<10}{'model n':>9}{'said':>8}{'actual':>8}{'market n':>10}{'said':>8}{'actual':>8}"]
        for row in calibration:
            lines.append(
                f"    {row['bucket']:<10}{row['model_count']:>9}{_p(row['model_avg_p']):>8}"
                f"{_p(row['model_yes_rate']):>8}{row['market_count']:>10}{_p(row['market_avg_p']):>8}"
                f"{_p(row['market_yes_rate']):>8}"
            )
    lines += _skip_lines(p, "Skipped markets")
    if p.get("halted"):
        lines += ["", "  !! Kill switch tripped: max_drawdown_pct reached; betting stopped."]
    if p.get("sample_data"):
        lines += ["", *textwrap.wrap("NOTE: " + SAMPLE_PRICES_NOTE, WIDTH - 4,
                                     initial_indent="  ", subsequent_indent="  ")]
    return lines


def _p(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.0%}"


def _skip_lines(p: Dict[str, Any], title: str) -> List[str]:
    reasons = p.get("skip_reasons") or {}
    lines = ["", f"  {title} ({sum(reasons.values())}) - logged with reasons"]
    if not reasons:
        lines.append("    none")
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        lines.append(_row(reason, str(count)))
    return lines


# --- HTML report -----------------------------------------------------------

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --good: #006300; --bad: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --good: #0ca30c; --bad: #e66767;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --good: #0ca30c; --bad: #e66767;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 48px; }
.banner { border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; font-weight: 600;
  background: var(--surface); margin-bottom: 16px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 32px 0 8px; }
.sub { color: var(--ink-2); margin: 0 0 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.tile .label { color: var(--ink-2); font-size: 13px; }
.tile .value { font-size: 22px; font-weight: 600; }
.tile .note { color: var(--muted); font-size: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; position: relative; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; color: var(--ink-2); font-size: 13px; margin-bottom: 4px; }
.key { display: inline-block; width: 16px; height: 2px; vertical-align: middle; margin-right: 6px; }
svg { width: 100%; height: auto; display: block; }
svg text { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
svg .direct { font-size: 12px; fill: var(--ink-2); }
.tip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 8px; font-size: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); display: none;
  white-space: nowrap; }
.tip b { font-variant-numeric: tabular-nums; }
.table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th { color: var(--ink-2); font-weight: 600; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.win td.pnl { color: var(--good); } tr.loss td.pnl { color: var(--bad); }
footer { color: var(--muted); font-size: 13px; margin-top: 32px; }
"""

JS = """
document.querySelectorAll('.chart').forEach(function (card) {
  var data = JSON.parse(card.querySelector('script').textContent);
  var svg = card.querySelector('svg'), tip = card.querySelector('.tip');
  var hair = svg.querySelector('.hair');
  function show(evt) {
    var box = svg.getBoundingClientRect();
    var x = (evt.clientX - box.left) / box.width * data.w;
    var t = (x - data.left) / (data.w - data.left - data.right);
    var i = Math.max(0, Math.min(data.dates.length - 1, Math.round(t * (data.dates.length - 1))));
    var px = data.left + i / Math.max(1, data.dates.length - 1) * (data.w - data.left - data.right);
    hair.setAttribute('x1', px); hair.setAttribute('x2', px); hair.style.display = '';
    tip.textContent = '';
    var head = document.createElement('div'); head.textContent = data.dates[i]; tip.appendChild(head);
    data.series.forEach(function (s) {
      var row = document.createElement('div');
      var key = document.createElement('span'); key.className = 'key'; key.style.background = s.color;
      var val = document.createElement('b'); val.textContent = s.fmt[i] + ' ';
      var name = document.createElement('span'); name.textContent = s.name;
      row.appendChild(key); row.appendChild(val); row.appendChild(name); tip.appendChild(row);
    });
    tip.style.display = 'block';
    var left = (px / data.w) * box.width + 12;
    if (left + tip.offsetWidth > box.width) left -= tip.offsetWidth + 24;
    tip.style.left = left + 'px'; tip.style.top = '40px';
  }
  svg.addEventListener('pointermove', show);
  svg.addEventListener('pointerleave', function () { tip.style.display = 'none'; hair.style.display = 'none'; });
});
"""


def _downsample(points: Sequence[Tuple[datetime, Sequence[float]]], max_points: int = 1200):
    if len(points) <= max_points:
        return list(points)
    step = len(points) / max_points
    picked = [points[int(k * step)] for k in range(max_points)]
    picked[-1] = points[-1]
    return picked


def _nice_ticks(lo: float, hi: float, log: bool) -> List[float]:
    if log:
        ticks = []
        for exp in range(int(math.floor(math.log10(lo))), int(math.ceil(math.log10(hi))) + 1):
            for mult in (1, 2, 5):
                value = mult * 10 ** exp
                if lo <= value <= hi:
                    ticks.append(value)
        if len(ticks) > 8:
            ticks = [t for t in ticks if str(int(t)).startswith("1")] or ticks
        return ticks or [lo, hi]
    raw = (hi - lo) / 5 or 1.0
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    start = math.ceil(lo / step) * step
    ticks = []
    value = start
    while value <= hi + 1e-9:
        ticks.append(round(value, 10))
        value += step
    return ticks


def _axis_label(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value:.0f}%"
    if abs(value) >= 1e6:
        return f"${value / 1e6:.1f}M"
    if abs(value) >= 1e4:
        return f"${value / 1e3:.0f}k"
    return f"${value:,.0f}"


def line_chart(chart_id: str, dates: List[datetime], series: List[Dict[str, Any]], unit: str = "$",
               allow_log: bool = True) -> str:
    """One-axis SVG line chart with a crosshair tooltip. series: [{name, values, color_var}]."""
    points = _downsample(list(zip(dates, zip(*[s["values"] for s in series]))))
    dates = [d for d, _ in points]
    columns = [[vals[k] for _, vals in points] for k in range(len(series))]
    w, h, left, right, top, bottom = 820, 280, 64, 110, 14, 26
    all_values = [v for col in columns for v in col]
    lo, hi = min(all_values), max(all_values)
    log = allow_log and lo > 0 and hi / lo > 4
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    f = (lambda v: math.log10(v)) if log else (lambda v: v)
    flo, fhi = f(lo), f(hi)
    pad = (fhi - flo) * 0.05
    flo, fhi = flo - pad, fhi + pad

    def x_at(i: int) -> float:
        return left + i / max(1, len(dates) - 1) * (w - left - right)

    def y_at(v: float) -> float:
        return top + (fhi - f(v)) / (fhi - flo) * (h - top - bottom)

    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="{chart_id}-title">']
    tick_lo, tick_hi = (10 ** flo, 10 ** fhi) if log else (flo, fhi)
    for tick in _nice_ticks(tick_lo, tick_hi, log):
        y = y_at(tick)
        parts.append(f'<line x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{html.escape(_axis_label(tick, unit))}</text>')
    if unit == "%" and flo <= 0 <= fhi:
        parts.append(f'<line x1="{left}" x2="{w - right}" y1="{y_at(0):.1f}" y2="{y_at(0):.1f}" stroke="var(--axis)"/>')
    for k in range(6):
        i = round(k / 5 * (len(dates) - 1))
        anchor = "start" if k == 0 else ("end" if k == 5 else "middle")
        parts.append(f'<text x="{x_at(i):.1f}" y="{h - 6}" text-anchor="{anchor}">{dates[i].date().isoformat()}</text>')

    label_ys: List[float] = []
    for s, col in zip(series, columns):
        path = " ".join(f"{'M' if i == 0 else 'L'}{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(col))
        parts.append(f'<path d="{path}" fill="none" stroke="var({s["color_var"]})" stroke-width="2" '
                     'stroke-linejoin="round" stroke-linecap="round"/>')
        y_label = y_at(col[-1])
        for other in label_ys:  # keep direct labels from overlapping
            if abs(y_label - other) < 14:
                y_label = other + 14 if y_label >= other else other - 14
        label_ys.append(y_label)
        parts.append(f'<text class="direct" x="{w - right + 8}" y="{y_label + 4:.1f}">{html.escape(s["name"])}</text>')
    parts.append(f'<line class="hair" x1="0" x2="0" y1="{top}" y2="{h - bottom}" stroke="var(--axis)" style="display:none"/>')
    parts.append("</svg>")

    fmt = (lambda v: f"{v:.2f}%") if unit == "%" else (lambda v: f"${v:,.2f}")
    data = {
        "w": w, "left": left, "right": right,
        "dates": [d.strftime("%Y-%m-%d %H:%M") if d.hour else d.date().isoformat() for d in dates],
        "series": [{"name": s["name"], "color": f"var({s['color_var']})", "fmt": [fmt(v) for v in col]}
                   for s, col in zip(series, columns)],
    }
    legend = ""
    if len(series) > 1:
        legend = '<div class="legend">' + "".join(
            f'<span><span class="key" style="background:var({s["color_var"]})"></span>{html.escape(s["name"])}</span>'
            for s in series) + "</div>"
    scale_note = " (log scale)" if log else ""
    safe_json = json.dumps(data).replace("</", "<\\/")  # can't close the <script> tag early
    return (f'<div class="card chart"><div class="legend" id="{chart_id}-title" style="margin:0">'
            f'{html.escape(series[0].get("title", ""))}{scale_note}</div>{legend}{"".join(parts)}'
            f'<div class="tip"></div><script type="application/json">{safe_json}</script></div>')


def _tiles(tiles: List[Tuple[str, str, str]]) -> str:
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="label">{html.escape(label)}</div>'
        f'<div class="value">{html.escape(value)}</div><div class="note">{html.escape(note)}</div></div>'
        for label, value, note in tiles) + "</div>"


def _table(headers: List[str], rows: List[List[Any]], numeric: Sequence[int] = (),
           classes: Optional[List[str]] = None, pnl_cols: Sequence[int] = ()) -> str:
    """HTML table. `classes` marks rows win/loss; only the `pnl_cols` cells take the color."""
    if not rows:
        return '<p class="sub">None.</p>'

    def cell_class(k: int) -> str:
        names = (["num"] if k in numeric else []) + (["pnl"] if k in pnl_cols else [])
        return f' class="{" ".join(names)}"' if names else ""

    num_attr = ' class="num"'
    head = "".join(f"<th{num_attr if k in numeric else ''}>{html.escape(h)}</th>" for k, h in enumerate(headers))
    body = []
    for r, row in enumerate(rows):
        row_class = f' class="{classes[r]}"' if classes and classes[r] else ""
        cells = "".join(f"<td{cell_class(k)}>{html.escape(str(c))}</td>" for k, c in enumerate(row))
        body.append(f"<tr{row_class}>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _page(title: str, subtitle: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>"
        "<div class='banner'>PAPER MODE ONLY &mdash; simulated trades, no real money, no orders sent.</div>"
        f"<h1>{html.escape(title)}</h1><p class='sub'>{html.escape(subtitle)}</p>{body}"
        "<footer>Backtests describe the past on one dataset. They do not predict future returns.</footer>"
        f"</main><script>{JS}</script></body></html>"
    )


def _drawdown_series(values: Sequence[float]) -> List[float]:
    peak = -math.inf
    out = []
    for v in values:
        peak = max(peak, v)
        out.append(-(peak - v) / peak * 100.0 if peak > 0 else 0.0)
    return out


HTML_TABLE_ROWS = 50  # the full lists are in round_trips.csv / bets.csv


def _when(iso: str) -> str:
    """'2017-08-12T00:00:00+00:00' -> '2017-08-12'; keep the time for intraday bars."""
    day, _, time = iso.partition("T")
    return day if time.startswith("00:00:00") else f"{day} {time[:5]}"


def write_backtest_html(result, payload: Dict[str, Any], path: Path) -> None:
    m = result.metrics
    dates = [t for t, _ in result.equity_curve]
    equity = [v for _, v in result.equity_curve]
    bench = [v for _, v in result.benchmark_curve]
    tiles = _tiles([
        ("Total return", pct(m["total_return_pct"]), f"buy & hold {pct(m['buy_hold_return_pct'])}"),
        ("Max drawdown", pct(-m["max_drawdown_pct"]), f"buy & hold {pct(-m['buy_hold_max_drawdown_pct'])}"),
        ("Sharpe ratio", num(m["sharpe"]), "risk-adjusted return"),
        ("Trades", str(m["trades"]), f"win rate {pct(m['win_rate_pct'], signed=False)}"),
        ("Skipped signals", str(m["skipped_signals"]), "blocked by risk or volatility"),
        ("Fees paid", money(m["total_fees"]), f"in market {pct(m['exposure_pct'], signed=False)} of the time"),
    ])
    equity_chart = line_chart("equity", dates, [
        {"name": "Strategy", "values": equity, "color_var": "--series-1", "title": "Account value"},
        {"name": "Buy & hold", "values": bench, "color_var": "--series-2"},
    ])
    dd_chart = line_chart("drawdown", dates, [
        {"name": "Drawdown", "values": _drawdown_series(equity), "color_var": "--series-1",
         "title": "Strategy drawdown from its previous peak"},
    ], unit="%", allow_log=False)
    skip_rows = [[reason, count] for reason, count in sorted(result.skip_reasons.items(), key=lambda kv: -kv[1])]
    trades = result.round_trips[-HTML_TABLE_ROWS:]
    trade_rows = [[_when(t["entry_time"]), _when(t["exit_time"]),
                   f"{t['entry_price']:,.2f}", f"{t['exit_price']:,.2f}", money(t["pnl"], True),
                   pct(t["pnl_pct"]), t["bars_held"], t["exit_reason"]] for t in reversed(trades)]
    body = (
        tiles
        + "<h2>Account value vs buying and holding BTC</h2>" + equity_chart
        + "<h2>Drawdown</h2>" + dd_chart
        + "<h2>Skipped signals</h2><p class='sub'>Signals the strategy wanted to take but the risk "
          "manager or volatility filter blocked. Every one is in the trade log.</p>"
        + _table(["Reason", "Count"], skip_rows, numeric=[1])
        + f"<h2>Completed trades (latest {len(trades)} of {len(result.round_trips)})</h2>"
        + "<p class='sub'>The full list is in round_trips.csv next to this report.</p>"
        + _table(["Entry", "Exit", "Entry price", "Exit price", "P&L", "P&L %", "Bars", "Exit reason"],
                 trade_rows, numeric=[2, 3, 4, 5, 6], pnl_cols=[4, 5],
                 classes=["win" if t["pnl"] > 0 else "loss" for t in reversed(trades)])
    )
    subtitle = f"{result.strategy} on {result.data_label}, {m['start_date']} to {m['end_date']}. Run {result.run_id}."
    path.write_text(_page("BTC paper backtest", subtitle, body), encoding="utf-8")


def write_prediction_html(result, payload: Dict[str, Any], path: Path) -> None:
    m = result.metrics
    dates = [t for t, _ in result.equity_curve]
    equity = [v for _, v in result.equity_curve]
    tiles = _tiles([
        ("Total return", pct(m["total_return_pct"]), f"{money(m['start_equity'])} -> {money(m['end_equity'])}"),
        ("Max drawdown", pct(-m["max_drawdown_pct"]), "from the previous peak"),
        ("Bets", str(m["bets"]), f"win rate {pct(m['win_rate_pct'], signed=False)}"),
        ("Skipped markets", str(m["skipped_markets"]), "no edge, filtered or limited"),
        ("Brier: model", num(m["brier_model"], 4), "lower is better"),
        ("Brier: market", num(m["brier_market"], 4), "0.25 = coin flip"),
    ])
    chart = line_chart("bankroll", dates, [
        {"name": "Bankroll", "values": equity, "color_var": "--series-1", "title": "Bankroll after each bet and payout"},
    ], allow_log=False) if len(dates) > 1 else "<p class='sub'>No bets placed.</p>"
    cal_rows = [[r["bucket"], r["model_count"], _p(r["model_avg_p"]), _p(r["model_yes_rate"]),
                 r["market_count"], _p(r["market_avg_p"]), _p(r["market_yes_rate"])] for r in result.calibration]
    skip_rows = [[reason, count] for reason, count in sorted(result.skip_reasons.items(), key=lambda kv: -kv[1])]
    bets = result.bets[-HTML_TABLE_ROWS:]
    bet_rows = [[b["decision_time"][:10], b["question"] or b["market_id"], b["side"], b["contracts"],
                 f"{b['price']:.2f}", f"{b['model_p_yes']:.2f}", f"{b['yes_price']:.2f}", money(b["pnl"], True)]
                for b in reversed(bets)]
    body = (
        tiles + "<h2>Bankroll</h2>" + chart
        + "<h2>Calibration</h2><p class='sub'>When a forecast said X%, how often did YES actually happen? "
          "Well-calibrated forecasts have 'said' close to 'actual'.</p>"
        + _table(["Bucket", "Model n", "Model said", "Actual", "Market n", "Market said", "Actual"],
                 cal_rows, numeric=[1, 2, 3, 4, 5, 6])
        + "<h2>Skipped markets</h2>" + _table(["Reason", "Count"], skip_rows, numeric=[1])
        + f"<h2>Settled bets (latest {len(bets)} of {len(result.bets)})</h2>"
        + "<p class='sub'>The full list is in bets.csv next to this report.</p>"
        + _table(["Decided", "Market", "Side", "Contracts", "Paid", "Model P(yes)", "Market P(yes)", "P&L"],
                 bet_rows, numeric=[3, 4, 5, 6, 7], pnl_cols=[7],
                 classes=["win" if b["won"] else "loss" for b in reversed(bets)])
    )
    subtitle = f"{result.data_label}, {m['start_date']} to {m['end_date']}. Run {result.run_id}."
    if payload.get("sample_data"):
        body = f"<div class='banner'>{html.escape(SAMPLE_PRICES_NOTE)}</div>" + body
    path.write_text(_page("Prediction-market paper experiment", subtitle, body), encoding="utf-8")
