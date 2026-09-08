"""Assembles the ML feature matrix from Phase 4's team_features/
match_features + the fixture's own over_2_5 target.

One row per fixture: the home team's TeamFeatures columns prefixed
`home_`, the away team's prefixed `away_`, and MatchFeatures' league/h2h
columns as-is. `build_training_matrix` requires a known result
(`Fixture.over_2_5 IS NOT NULL`) — training needs labels.
`build_feature_row_for_fixture` does not — a not-yet-played fixture still
needs a feature row to predict on.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, aliased

from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.models.utils import row_to_dict

TEAM_FEATURES_EXCLUDE = frozenset(
    {"id", "team_id", "fixture_id", "is_home", "as_of", "feature_version", "computed_at", "created_at", "updated_at"}
)
MATCH_FEATURES_EXCLUDE = frozenset({"fixture_id", "feature_version", "computed_at", "created_at", "updated_at"})

# Columns present in build_training_matrix's output that are NOT model
# features - fixture identity/metadata and the target itself.
META_COLUMNS = frozenset({"fixture_id", "kickoff", "league_id", "over_2_5"})


def assemble_feature_row(home_features: TeamFeatures, away_features: TeamFeatures, match_features: MatchFeatures) -> dict:
    row: dict = {}
    for key, value in row_to_dict(home_features, exclude=TEAM_FEATURES_EXCLUDE).items():
        row[f"home_{key}"] = value
    for key, value in row_to_dict(away_features, exclude=TEAM_FEATURES_EXCLUDE).items():
        row[f"away_{key}"] = value
    row.update(row_to_dict(match_features, exclude=MATCH_FEATURES_EXCLUDE))
    return row


def build_feature_row_for_fixture(session: Session, fixture: Fixture) -> dict | None:
    home_features = session.execute(
        select(TeamFeatures).where(
            TeamFeatures.fixture_id == fixture.id, TeamFeatures.team_id == fixture.home_team_id
        )
    ).scalar_one_or_none()
    away_features = session.execute(
        select(TeamFeatures).where(
            TeamFeatures.fixture_id == fixture.id, TeamFeatures.team_id == fixture.away_team_id
        )
    ).scalar_one_or_none()
    match_features = session.execute(
        select(MatchFeatures).where(MatchFeatures.fixture_id == fixture.id)
    ).scalar_one_or_none()

    if home_features is None or away_features is None or match_features is None:
        return None
    return assemble_feature_row(home_features, away_features, match_features)


def build_training_matrix(session: Session, *, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """One row per fixture in [start_date, end_date) with a known result
    and computed features, ordered by kickoff (never shuffled - callers
    that need a train/val/test split use chronological_split on this)."""
    home_alias = aliased(TeamFeatures)
    away_alias = aliased(TeamFeatures)

    stmt = (
        select(Fixture, home_alias, away_alias, MatchFeatures)
        .join(home_alias, and_(home_alias.fixture_id == Fixture.id, home_alias.team_id == Fixture.home_team_id))
        .join(away_alias, and_(away_alias.fixture_id == Fixture.id, away_alias.team_id == Fixture.away_team_id))
        .join(MatchFeatures, MatchFeatures.fixture_id == Fixture.id)
        .where(
            Fixture.kickoff >= start_date,
            Fixture.kickoff < end_date,
            Fixture.over_2_5.isnot(None),
        )
        .order_by(Fixture.kickoff)
    )

    records = []
    for fixture, home_features, away_features, match_features in session.execute(stmt).all():
        record = assemble_feature_row(home_features, away_features, match_features)
        record["fixture_id"] = fixture.id
        record["kickoff"] = fixture.kickoff
        record["league_id"] = fixture.league_id
        record["over_2_5"] = int(fixture.over_2_5)
        records.append(record)

    return pd.DataFrame.from_records(records)
