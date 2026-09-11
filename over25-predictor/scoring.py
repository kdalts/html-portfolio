"""
Turns a MatchContext (+ its parent Fixture) into one output CSV row, and
writes the full set of rows to disk.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from checks import SCORED_CHECKS, MatchContext, context_notes, key_players_missing
from fixtures import Fixture

log = logging.getLogger("over25.scoring")

CSV_COLUMNS = (
    ["date", "kick_off_time", "league", "country", "home_team", "away_team",
     "checks_passed", "checks_computable", "score_pct"]
    + [name for name, _ in SCORED_CHECKS]
    + ["key_players_missing", "context_notes", "data_gaps"]
)


def _fmt(result_passed) -> str:
    if result_passed is True:
        return "TRUE"
    if result_passed is False:
        return "FALSE"
    return "N/A"


def score_fixture(fixture: Fixture, ctx: MatchContext) -> dict:
    row = {
        "date": fixture.date,
        "kick_off_time": fixture.kick_off_time,
        "league": fixture.league_name,
        "country": fixture.country,
        "home_team": fixture.home_team_name,
        "away_team": fixture.away_team_name,
    }

    passed_count = 0
    computable_count = 0
    data_gap_notes = []

    for col_name, check_fn in SCORED_CHECKS:
        result = check_fn(ctx)
        row[col_name] = _fmt(result.passed)
        if result.passed is not None:
            computable_count += 1
            if result.passed:
                passed_count += 1
        elif result.note:
            data_gap_notes.append(f"{col_name}: {result.note}")

    row["checks_passed"] = passed_count
    row["checks_computable"] = computable_count
    row["score_pct"] = round(100 * passed_count / computable_count, 1) if computable_count else 0.0

    row["key_players_missing"] = key_players_missing(ctx.home, ctx.away)
    row["context_notes"] = context_notes(ctx)

    data_gap_notes.extend(ctx.home.data_gaps)
    data_gap_notes.extend(ctx.away.data_gaps)
    row["data_gaps"] = "; ".join(data_gap_notes) if data_gap_notes else ""

    return row


def sort_rows(rows: list) -> list:
    return sorted(rows, key=lambda r: (r["score_pct"], r["checks_passed"]), reverse=True)


def write_csv(rows: list, output_dir: str, filename: str) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    log.info("Wrote %d rows to %s", len(rows), out_path)
    return out_path
