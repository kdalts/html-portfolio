"""
Builds a single self-contained HTML report from the same row data that goes
into the CSV -- sortable columns, colour-coded TRUE/FALSE/N/A, and simple
client-side filters (league, minimum score, team search). No server and no
external dependencies: double-click the file to open it in a browser.

Kept dependency-free (no Jinja2) since this is a small, fixed template.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from checks import SCORED_CHECKS

log = logging.getLogger("over25.html_report")

CHECK_LABELS = {
    "check_1": ("1. Sample size", "Both teams have played 5+ games this season (gate check)"),
    "check_2": ("2. BTTS rate", "Each team's BTTS rate this season is over 60%"),
    "check_3": ("3. Clean sheets", "Each team's clean sheet rate is below 35%"),
    "check_4": ("4. Combined GPG", "Home GPG + away GPG is over 3.5"),
    "check_5": ("5. League gap", "Home team is 5+ places higher in the table"),
    "check_6": ("6. Shots on target", "Both teams average more than 4 shots on target/game"),
    "check_7": ("7. Attack vs defence", "Home GF avg > 3 AND away GA avg > 3"),
    "check_8": ("8. xG", "Combined expected-goals estimate exceeds 2.5 (approximation, see README)"),
    "check_9": ("9. H2H", "Last 3 head-to-head meetings were all over 2.5 goals"),
    "check_10": ("10. Recent form", "60%+ of each team's last 5 games were over 2.5 goals"),
    "check_11": ("11. Vs league avg", "Each team's GPG is higher than their league's average GPG"),
    "check_12": ("12. Early goals", "Each team scores in the first 15 minutes in 40%+ of games"),
    "check_13": ("13. Late goals", "Each team scores in the last 15 minutes in 40%+ of games"),
}

CHECK_COLUMNS = [name for name, _ in SCORED_CHECKS]

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Over 2.5 Predictions - {report_date}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #f6f7f9; --panel: #ffffff; --text: #1c2128; --muted: #6b7280;
    --border: #e2e5ea; --true-bg: #d9f2e3; --true-text: #146c3f;
    --false-bg: #fbe3e3; --false-text: #9c2c2c; --na-bg: #eef0f3; --na-text: #6b7280;
    --accent: #2b6cff; --row-hover: #f0f4ff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #14161a; --panel: #1c1f26; --text: #e6e8eb; --muted: #9aa1ac;
      --border: #2c313a; --true-bg: #14351f; --true-text: #7be0a1;
      --false-bg: #3a1a1a; --false-text: #f3a3a3; --na-bg: #262a31; --na-text: #8b929c;
      --accent: #6c9bff; --row-hover: #232838;
    }}
  }}
  :root[data-theme="dark"] {{
    --bg: #14161a; --panel: #1c1f26; --text: #e6e8eb; --muted: #9aa1ac;
    --border: #2c313a; --true-bg: #14351f; --true-text: #7be0a1;
    --false-bg: #3a1a1a; --false-text: #f3a3a3; --na-bg: #262a31; --na-text: #8b929c;
    --accent: #6c9bff; --row-hover: #232838;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 20px 16px 40px; background: var(--bg); color: var(--text);
    font: 14px/1.4 -apple-system, Segoe UI, Roboto, Arial, sans-serif;
  }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); margin: 0 0 18px; font-size: 13px; }}
  .summary {{
    display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 18px;
  }}
  .stat {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 10px 16px; min-width: 120px;
  }}
  .stat .value {{ font-size: 20px; font-weight: 700; }}
  .stat .label {{ color: var(--muted); font-size: 12px; }}
  .controls {{
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px;
  }}
  .controls input, .controls select {{
    background: var(--panel); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 7px 10px; font-size: 13px;
  }}
  .controls label {{ font-size: 12px; color: var(--muted); }}
  .table-wrap {{
    overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--panel);
  }}
  table {{ border-collapse: collapse; width: 100%; min-width: 1200px; }}
  th, td {{ padding: 7px 10px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }}
  th {{
    position: sticky; top: 0; background: var(--panel); cursor: pointer; user-select: none;
    font-size: 12px; color: var(--muted); border-bottom: 2px solid var(--border);
  }}
  th:hover {{ color: var(--accent); }}
  th.sorted::after {{ content: " " attr(data-arrow); color: var(--accent); }}
  tbody tr:hover {{ background: var(--row-hover); }}
  td.notes {{ white-space: normal; max-width: 260px; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-weight: 600; font-size: 12px; }}
  .b-true {{ background: var(--true-bg); color: var(--true-text); }}
  .b-false {{ background: var(--false-bg); color: var(--false-text); }}
  .b-na {{ background: var(--na-bg); color: var(--na-text); font-weight: 500; }}
  .score-cell {{ font-weight: 700; }}
  .score-high {{ color: var(--true-text); }}
  .score-mid {{ color: #b8860b; }}
  .score-low {{ color: var(--muted); }}
  .hidden-row {{ display: none; }}
  .count-line {{ color: var(--muted); font-size: 12px; margin: 8px 0 0; }}
</style>
</head>
<body>
  <h1>Over 2.5 Goals Predictions</h1>
  <p class="subtitle">Generated {report_date} · Personal research tool, not a betting placement tool</p>

  <div class="summary">
    <div class="stat"><div class="value">{fixtures_scanned}</div><div class="label">Fixtures scanned</div></div>
    <div class="stat"><div class="value">{matches_scored}</div><div class="label">Matches scored</div></div>
    <div class="stat"><div class="value">{high_score_count}</div><div class="label">{high_score_threshold}+/13 checks</div></div>
    <div class="stat"><div class="value">{api_calls}</div><div class="label">API calls this run</div></div>
  </div>

  <div class="controls">
    <div>
      <label for="leagueFilter">League</label><br>
      <select id="leagueFilter"><option value="">All leagues</option></select>
    </div>
    <div>
      <label for="minScore">Min checks passed</label><br>
      <input type="number" id="minScore" min="0" max="13" value="0" style="width:70px">
    </div>
    <div>
      <label for="teamSearch">Search team</label><br>
      <input type="text" id="teamSearch" placeholder="e.g. Arsenal">
    </div>
  </div>

  <div class="table-wrap">
    <table id="resultsTable">
      <thead><tr>{header_html}</tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <p class="count-line" id="countLine"></p>

<script>
(function() {{
  var table = document.getElementById('resultsTable');
  var tbody = table.tBodies[0];
  var rows = Array.prototype.slice.call(tbody.rows);
  var headers = table.tHead.rows[0].cells;

  // Populate league filter from data
  var leagues = Array.from(new Set(rows.map(function(r) {{ return r.dataset.league; }}))).sort();
  var leagueSelect = document.getElementById('leagueFilter');
  leagues.forEach(function(l) {{
    var opt = document.createElement('option');
    opt.value = l; opt.textContent = l;
    leagueSelect.appendChild(opt);
  }});

  function applyFilters() {{
    var league = leagueSelect.value;
    var minScore = parseInt(document.getElementById('minScore').value || '0', 10);
    var search = document.getElementById('teamSearch').value.trim().toLowerCase();
    var visible = 0;
    rows.forEach(function(r) {{
      var okLeague = !league || r.dataset.league === league;
      var okScore = parseInt(r.dataset.passed, 10) >= minScore;
      var okSearch = !search || r.dataset.teams.indexOf(search) !== -1;
      var show = okLeague && okScore && okSearch;
      r.classList.toggle('hidden-row', !show);
      if (show) visible++;
    }});
    document.getElementById('countLine').textContent = visible + ' of ' + rows.length + ' rows shown';
  }}

  leagueSelect.addEventListener('change', applyFilters);
  document.getElementById('minScore').addEventListener('input', applyFilters);
  document.getElementById('teamSearch').addEventListener('input', applyFilters);
  applyFilters();

  // Sorting
  var sortState = {{ col: null, dir: 1 }};
  Array.prototype.forEach.call(headers, function(th, idx) {{
    th.addEventListener('click', function() {{
      var dir = (sortState.col === idx) ? -sortState.dir : 1;
      sortState = {{ col: idx, dir: dir }};
      Array.prototype.forEach.call(headers, function(h) {{ h.classList.remove('sorted'); h.removeAttribute('data-arrow'); }});
      th.classList.add('sorted');
      th.setAttribute('data-arrow', dir === 1 ? '\\u25B2' : '\\u25BC');

      var sorted = rows.slice().sort(function(a, b) {{
        var av = a.cells[idx].dataset.sort !== undefined ? a.cells[idx].dataset.sort : a.cells[idx].textContent;
        var bv = b.cells[idx].dataset.sort !== undefined ? b.cells[idx].dataset.sort : b.cells[idx].textContent;
        var an = parseFloat(av), bn = parseFloat(bv);
        var cmp;
        if (!isNaN(an) && !isNaN(bn) && (av === String(an) || av === String(bn) || !isNaN(av))) {{
          cmp = an - bn;
        }} else {{
          cmp = String(av).localeCompare(String(bv));
        }}
        return cmp * dir;
      }});
      sorted.forEach(function(r) {{ tbody.appendChild(r); }});
    }});
  }});
}})();
</script>
</body>
</html>
"""


def _badge(value: str) -> str:
    if value == "TRUE":
        return '<span class="badge b-true">TRUE</span>'
    if value == "FALSE":
        return '<span class="badge b-false">FALSE</span>'
    return '<span class="badge b-na">N/A</span>'


def _score_class(score_pct: float) -> str:
    if score_pct >= 75:
        return "score-high"
    if score_pct >= 50:
        return "score-mid"
    return "score-low"


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _build_header() -> str:
    cols = [
        ("Date", None), ("Time", None), ("League", None), ("Country", None),
        ("Home", None), ("Away", None), ("Score", None),
    ]
    cells = [f"<th>{label}</th>" for label, _ in cols]
    for check_col in CHECK_COLUMNS:
        short_label, tooltip = CHECK_LABELS[check_col]
        cells.append(f'<th title="{_esc(tooltip)}">{_esc(short_label)}</th>')
    cells.append("<th>Key players missing</th>")
    cells.append("<th>Context notes</th>")
    cells.append("<th>Data gaps</th>")
    return "".join(cells)


def _build_row(row: dict) -> str:
    score_pct = row["score_pct"]
    league = _esc(row["league"])
    teams_search = _esc(f"{row['home_team']} {row['away_team']}".lower())

    cells = [
        f'<td data-sort="{_esc(row["date"])}">{_esc(row["date"])}</td>',
        f'<td>{_esc(row["kick_off_time"])}</td>',
        f'<td>{league}</td>',
        f'<td>{_esc(row["country"])}</td>',
        f'<td>{_esc(row["home_team"])}</td>',
        f'<td>{_esc(row["away_team"])}</td>',
        f'<td class="score-cell {_score_class(score_pct)}" data-sort="{score_pct}">'
        f'{row["checks_passed"]}/{row["checks_computable"]} ({score_pct}%)</td>',
    ]
    for check_col in CHECK_COLUMNS:
        value = row.get(check_col, "N/A")
        sort_val = {"TRUE": 2, "FALSE": 0, "N/A": 1}[value]
        cells.append(f'<td data-sort="{sort_val}">{_badge(value)}</td>')

    cells.append(f'<td class="notes">{_esc(row["key_players_missing"])}</td>')
    cells.append(f'<td class="notes">{_esc(row["context_notes"])}</td>')
    cells.append(f'<td class="notes">{_esc(row["data_gaps"])}</td>')

    return (
        f'<tr data-league="{league}" data-passed="{row["checks_passed"]}" '
        f'data-teams="{teams_search}">' + "".join(cells) + "</tr>"
    )


def build_html(rows: list, report_date: str, fixtures_scanned: int, high_score_threshold: int,
                high_score_count: int, api_calls: int) -> str:
    header_html = _build_header()
    rows_html = "".join(_build_row(r) for r in rows)
    return PAGE_TEMPLATE.format(
        report_date=_esc(report_date),
        fixtures_scanned=fixtures_scanned,
        matches_scored=len(rows),
        high_score_threshold=high_score_threshold,
        high_score_count=high_score_count,
        api_calls=api_calls,
        header_html=header_html,
        rows_html=rows_html or '<tr><td colspan="99">No matches met the minimum sample-size requirement.</td></tr>',
    )


def write_html_report(
    rows: list,
    output_dir: str,
    filename: str,
    report_date: str,
    fixtures_scanned: int,
    high_score_threshold: int,
    high_score_count: int,
    api_calls: int,
) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    content = build_html(
        rows, report_date, fixtures_scanned, high_score_threshold, high_score_count, api_calls
    )
    out_path.write_text(content, encoding="utf-8")
    log.info("Wrote HTML report (%d rows) to %s", len(rows), out_path)
    return out_path
