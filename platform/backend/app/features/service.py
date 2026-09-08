"""Orchestrates feature computation and storage for fixtures.

Unlike ingestion, this works for fixtures of ANY status — an upcoming,
not-yet-played fixture needs team_features/match_features computed for it
just as much as a historical one does (that's what the daily ranking will
read). What matters is only ever using appearances/matches strictly
before that fixture's own kickoff, which app.features.rolling and
app.features.league_features/h2h_features enforce.

Each fixture is processed inside its own SAVEPOINT, matching the
ingestion pipeline's error-isolation pattern: one fixture with unusable
data (e.g. teams sharing no resolvable history) is skipped and recorded
in the returned BatchSummary rather than aborting the whole run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.common.batch import BatchSummary
from app.db.models.fixtures import Fixture
from app.features import repository
from app.features.h2h_features import compute_h2h_features
from app.features.league_features import compute_league_features
from app.features.rolling import compute_team_rolling_features
from app.features.team_match_log import TeamAppearance, fetch_team_appearances

logger = logging.getLogger(__name__)

FEATURE_VERSION = "v1"


def _completeness_score(home_rolling: dict, away_rolling: dict) -> float:
    """A simple, documented placeholder heuristic: how much of the
    "last 10 matches" window is actually filled in, averaged across both
    teams. Phase 11 (ranking/confidence) is free to define a more
    sophisticated data-quality signal; this is a reasonable default in
    the meantime and always in [0, 1]."""
    home_fraction = min(home_rolling["overall_last10_matches_played"], 10) / 10
    away_fraction = min(away_rolling["overall_last10_matches_played"], 10) / 10
    return (home_fraction + away_fraction) / 2


def compute_features_for_fixture(
    session: Session,
    fixture: Fixture,
    *,
    appearance_cache: dict[int, list[TeamAppearance]] | None = None,
) -> tuple[dict, dict, dict]:
    """Returns (home_team_features_values, away_team_features_values,
    match_features_values) as dicts ready for the repository upserts."""
    cache = appearance_cache if appearance_cache is not None else {}

    def appearances_for(team_id: int) -> list[TeamAppearance]:
        if team_id not in cache:
            cache[team_id] = fetch_team_appearances(session, team_id)
        return cache[team_id]

    home_rolling = compute_team_rolling_features(
        appearances_for(fixture.home_team_id), before=fixture.kickoff, target_is_home=True
    )
    away_rolling = compute_team_rolling_features(
        appearances_for(fixture.away_team_id), before=fixture.kickoff, target_is_home=False
    )

    now = datetime.now(timezone.utc)
    home_values = {
        "team_id": fixture.home_team_id,
        "fixture_id": fixture.id,
        "is_home": True,
        "as_of": fixture.kickoff,
        "feature_version": FEATURE_VERSION,
        "computed_at": now,
        **home_rolling,
    }
    away_values = {
        "team_id": fixture.away_team_id,
        "fixture_id": fixture.id,
        "is_home": False,
        "as_of": fixture.kickoff,
        "feature_version": FEATURE_VERSION,
        "computed_at": now,
        **away_rolling,
    }

    league_values = compute_league_features(
        session, league_id=fixture.league_id, season_id=fixture.season_id, before=fixture.kickoff
    )
    h2h_values = compute_h2h_features(
        session, team_a=fixture.home_team_id, team_b=fixture.away_team_id, before=fixture.kickoff
    )
    match_values = {
        "fixture_id": fixture.id,
        **league_values,
        **h2h_values,
        "feature_version": FEATURE_VERSION,
        "computed_at": now,
        "data_completeness_score": _completeness_score(home_rolling, away_rolling),
    }

    return home_values, away_values, match_values


def compute_and_store_features_for_fixtures(
    session: Session, fixtures: list[Fixture], *, commit: bool = True
) -> BatchSummary:
    summary = BatchSummary()
    cache: dict[int, list[TeamAppearance]] = {}

    for fixture in fixtures:
        summary.fetched += 1
        try:
            with session.begin_nested():
                home_values, away_values, match_values = compute_features_for_fixture(
                    session, fixture, appearance_cache=cache
                )
                repository.upsert_team_features(session, home_values)
                repository.upsert_team_features(session, away_values)
                repository.upsert_match_features(session, match_values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(fixture.id, exc)
            logger.warning("Failed to compute features for fixture %s: %s", fixture.id, exc)

    if commit:
        session.commit()
    return summary
