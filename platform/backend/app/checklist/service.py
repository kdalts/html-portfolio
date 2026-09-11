"""Orchestrates the 15-point checklist: gathers each team's current-season
history and this matchup's head-to-head/standings context, calls the pure
check functions in app/checklist/checks.py, and stores the result.

"Current season" scoping follows the checklist spec's own stated default
("using each team's current-season data unless noted") for every check
except #10 (recent form), which the spec states explicitly as "last 5
games" with no season qualifier - implemented here as literally the most
recent 5 appearances, which may cross a season boundary.

Per spec item 1: a fixture where either team has fewer than
MIN_SEASON_GAMES games played this season is excluded entirely, not
scored with N/A - `compute_checklist_for_fixture` returns None for
exactly this case, and the batch driver records it as a (expected,
not a bug) failure, same pattern as every other "insufficient data"
case elsewhere in this codebase (see poisson_service.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.checklist import checks
from app.checklist.standings import StandingsRow, compute_league_standings
from app.common.batch import BatchSummary
from app.common.upsert import upsert_one
from app.db.models.checklist import ChecklistScore
from app.db.models.features import MatchFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League
from app.features.team_match_log import TeamAppearance, fetch_team_appearances

logger = logging.getLogger(__name__)

MIN_SEASON_GAMES = 5
RECENT_FORM_WINDOW = 5
RELEGATION_ZONE_SIZE = 3
CUP_KEYWORDS = ("cup", "trophy", "shield", "playoff", "play-off")


def _average(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return (sum(present) / len(present)) if present else None


@dataclass(frozen=True)
class _TeamSeasonStats:
    games_played: int
    goals_for_per_game: float | None
    goals_against_per_game: float | None
    total_goals_per_game: float | None
    btts_rate: float | None
    clean_sheet_rate: float | None
    shots_on_target_avg: float | None
    xg_for_avg: float | None
    xg_against_avg: float | None


def _compute_season_stats(appearances: list[TeamAppearance]) -> _TeamSeasonStats:
    if not appearances:
        return _TeamSeasonStats(0, None, None, None, None, None, None, None, None)
    return _TeamSeasonStats(
        games_played=len(appearances),
        goals_for_per_game=_average([a.goals_for for a in appearances]),
        goals_against_per_game=_average([a.goals_against for a in appearances]),
        total_goals_per_game=_average([a.goals_for + a.goals_against for a in appearances]),
        btts_rate=_average([1.0 if (a.goals_for > 0 and a.goals_against > 0) else 0.0 for a in appearances]),
        clean_sheet_rate=_average([1.0 if a.goals_against == 0 else 0.0 for a in appearances]),
        shots_on_target_avg=_average([a.shots_on_target_for for a in appearances]),
        xg_for_avg=_average([a.xg_for for a in appearances]),
        xg_against_avg=_average([a.xg_against for a in appearances]),
    )


def _recent_form_over25_pct(
    appearances: list[TeamAppearance], *, before: datetime, window: int = RECENT_FORM_WINDOW
) -> float | None:
    prior = sorted([a for a in appearances if a.kickoff < before], key=lambda a: a.kickoff, reverse=True)[:window]
    if len(prior) < window:
        return None
    flags = [1.0 if (a.goals_for + a.goals_against) >= 3 else 0.0 for a in prior]
    return sum(flags) / len(flags)


def _h2h_last3_total_goals(session: Session, *, team_a: int, team_b: int, before: datetime) -> list[int] | None:
    rows = session.execute(
        select(Fixture.total_goals)
        .where(
            Fixture.total_goals.isnot(None),
            Fixture.kickoff < before,
            or_(
                and_(Fixture.home_team_id == team_a, Fixture.away_team_id == team_b),
                and_(Fixture.home_team_id == team_b, Fixture.away_team_id == team_a),
            ),
        )
        .order_by(Fixture.kickoff.desc())
        .limit(3)
    ).all()
    if len(rows) < 3:
        return None
    return [row[0] for row in rows]


def _build_context_notes(
    league: League | None, home_row: StandingsRow | None, away_row: StandingsRow | None, total_teams: int
) -> str | None:
    notes: list[str] = []
    if league is not None and any(kw in league.name.lower() for kw in CUP_KEYWORDS):
        notes.append(f"cup/playoff competition ({league.name})")
    if total_teams > 0:
        for label, row in (("home", home_row), ("away", away_row)):
            if row is not None and row.position > total_teams - RELEGATION_ZONE_SIZE:
                notes.append(f"{label} team in a relegation-zone position ({row.position}/{total_teams})")
    return "; ".join(notes) if notes else None


def compute_checklist_for_fixture(session: Session, fixture: Fixture) -> dict | None:
    """Returns the checklist_scores values dict, or None if either team
    has fewer than MIN_SEASON_GAMES games played this season (per spec
    item 1: excluded entirely, not scored)."""
    home_all = fetch_team_appearances(session, fixture.home_team_id)
    away_all = fetch_team_appearances(session, fixture.away_team_id)

    home_season = [a for a in home_all if a.season_id == fixture.season_id and a.kickoff < fixture.kickoff]
    away_season = [a for a in away_all if a.season_id == fixture.season_id and a.kickoff < fixture.kickoff]

    if not checks.check_sample_size(len(home_season), len(away_season), min_games=MIN_SEASON_GAMES):
        return None

    home_stats = _compute_season_stats(home_season)
    away_stats = _compute_season_stats(away_season)

    standings = compute_league_standings(
        session, league_id=fixture.league_id, season_id=fixture.season_id, before=fixture.kickoff
    )
    home_row = standings.get(fixture.home_team_id)
    away_row = standings.get(fixture.away_team_id)

    match_features = session.execute(
        select(MatchFeatures).where(MatchFeatures.fixture_id == fixture.id)
    ).scalar_one_or_none()

    h2h_last3 = _h2h_last3_total_goals(
        session, team_a=fixture.home_team_id, team_b=fixture.away_team_id, before=fixture.kickoff
    )
    home_recent = _recent_form_over25_pct(home_all, before=fixture.kickoff)
    away_recent = _recent_form_over25_pct(away_all, before=fixture.kickoff)

    scored = {
        "sample_size_ok": True,
        "btts_rate_ok": checks.check_btts_rate(home_stats.btts_rate, away_stats.btts_rate),
        "clean_sheet_rate_ok": checks.check_clean_sheet_rate(home_stats.clean_sheet_rate, away_stats.clean_sheet_rate),
        "combined_goals_ok": checks.check_combined_goals(
            home_stats.total_goals_per_game, away_stats.total_goals_per_game
        ),
        "league_gap_ok": checks.check_league_gap(
            home_row.position if home_row else None, away_row.position if away_row else None
        ),
        "shots_on_target_ok": checks.check_shots_on_target(
            home_stats.shots_on_target_avg, away_stats.shots_on_target_avg
        ),
        "attack_defence_split_ok": checks.check_attack_defence_split(
            home_stats.goals_for_per_game, away_stats.goals_against_per_game
        ),
        "xg_ok": checks.check_combined_xg(
            home_stats.xg_for_avg, home_stats.xg_against_avg, away_stats.xg_for_avg, away_stats.xg_against_avg
        ),
        "h2h_ok": checks.check_h2h_last3(h2h_last3),
        "recent_form_ok": checks.check_recent_form(home_recent, away_recent),
        "vs_league_avg_ok": checks.check_vs_league_average(
            home_stats.goals_for_per_game,
            away_stats.goals_for_per_game,
            match_features.league_home_goals_avg if match_features else None,
            match_features.league_away_goals_avg if match_features else None,
        ),
        "early_goals_ok": checks.check_early_goals(None, None),
        "late_goals_ok": checks.check_late_goals(None, None),
    }

    checks_computable = sum(1 for v in scored.values() if v is not None)
    checks_passed = sum(1 for v in scored.values() if v is True)
    score_pct = (checks_passed / checks_computable) if checks_computable else None

    data_gaps: list[str] = []
    if home_stats.shots_on_target_avg is None or away_stats.shots_on_target_avg is None:
        data_gaps.append("shots-on-target not ingested for one or both teams (needs a --with-statistics backfill)")
    if home_stats.xg_for_avg is None or away_stats.xg_for_avg is None:
        data_gaps.append("xG not ingested for one or both teams (needs a --with-statistics backfill)")
    data_gaps.append("goal-timing data (early/late goals) is not ingested by this platform yet")
    if home_row is None or away_row is None:
        data_gaps.append("league standings unavailable for one or both teams")
    if h2h_last3 is None:
        data_gaps.append("fewer than 3 prior head-to-head meetings on record")

    league = session.execute(select(League).where(League.id == fixture.league_id)).scalar_one_or_none()
    context_notes = _build_context_notes(league, home_row, away_row, len(standings))

    return {
        "fixture_id": fixture.id,
        "computed_at": datetime.now(timezone.utc),
        **scored,
        "checks_passed": checks_passed,
        "checks_computable": checks_computable,
        "score_pct": score_pct,
        "key_players_missing": "Unknown",
        "context_notes": context_notes,
        "data_gaps": "; ".join(data_gaps) if data_gaps else None,
    }


def upsert_checklist_score(session: Session, values: dict) -> int:
    return upsert_one(session, ChecklistScore, values, conflict_columns=["fixture_id"])


def compute_and_store_checklist_for_fixtures(
    session: Session, fixtures: list[Fixture], *, commit: bool = True
) -> BatchSummary:
    summary = BatchSummary()
    for fixture in fixtures:
        summary.fetched += 1
        try:
            with session.begin_nested():
                values = compute_checklist_for_fixture(session, fixture)
                if values is None:
                    raise ValueError(
                        f"excluded: fewer than {MIN_SEASON_GAMES} games played this season by one or both teams"
                    )
                upsert_checklist_score(session, values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(fixture.id, exc)
            logger.warning("Failed to compute checklist for fixture %s: %s", fixture.id, exc)

    if commit:
        session.commit()
    return summary
