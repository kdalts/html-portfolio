"""Turns per-fixture evaluation rows (model output vs actual outcome,
plus league/season/home-away context) into the backtest_results rows
required for one model_type: overall, and sliced by league, season,
probability band, and home/away.

The home/away segment is a deliberate interpretive choice, documented
here because the spec's "results by ... home/away" instruction doesn't
map literally onto a total-goals market (there's no "home side" or "away
side" of an Over/Under bet). Each evaluated fixture is categorized
"home_leaning" or "away_leaning" by comparing that fixture's Poisson
expected_home_goals vs expected_away_goals — computed for every
evaluation row regardless of which model_type is actually being scored,
purely for this categorization. That answers "did the model expect the
home or away side to contribute more of the total goals", the closest
sensible analogue to a home/away split for a total-goals model, and lets
every model_type (including 'ml', which has no expected-goals output of
its own) be sliced the same way.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.backtest.metrics import compute_all_metrics
from app.backtest.probability_bands import assign_band
from app.db.models.evaluation import PROBABILITY_BANDS


@dataclass(frozen=True)
class EvalRow:
    fixture_id: int
    y_true: int
    y_prob: float
    league_id: int
    season_id: int
    home_leaning: bool | None = None


def build_segment_results(rows: list[EvalRow]) -> list[dict]:
    """Returns backtest_results value dicts (segment_type, segment_value,
    plus every metric column) for `rows`. The caller fills in
    backtest_run_id / model_type / the train-test date columns. A segment
    with zero matching rows is simply omitted, never emitted as an
    empty/null row."""
    results: list[dict] = []

    def _emit(segment_type: str, segment_value: str, subset: list[EvalRow]) -> None:
        if not subset:
            return
        y_true = [r.y_true for r in subset]
        y_prob = [r.y_prob for r in subset]
        results.append(
            {"segment_type": segment_type, "segment_value": segment_value, **compute_all_metrics(y_true, y_prob)}
        )

    _emit("overall", "ALL", rows)

    by_league: dict[int, list[EvalRow]] = {}
    by_season: dict[int, list[EvalRow]] = {}
    for row in rows:
        by_league.setdefault(row.league_id, []).append(row)
        by_season.setdefault(row.season_id, []).append(row)
    for league_id, subset in by_league.items():
        _emit("league", str(league_id), subset)
    for season_id, subset in by_season.items():
        _emit("season", str(season_id), subset)

    by_band: dict[str, list[EvalRow]] = {band: [] for band in PROBABILITY_BANDS}
    for row in rows:
        band = assign_band(row.y_prob)
        if band is not None:
            by_band[band].append(row)
    for band, subset in by_band.items():
        _emit("probability_band", band, subset)

    _emit("home_away", "home_leaning", [r for r in rows if r.home_leaning is True])
    _emit("home_away", "away_leaning", [r for r in rows if r.home_leaning is False])

    return results
