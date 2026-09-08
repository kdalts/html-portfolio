"""Idempotent upserts for every table ingestion writes to, built on the
shared `app.common.upsert.upsert_one`. See that module's docstring for
the generated-column caveat.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.upsert import upsert_one
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import MatchStatistics, MatchXG, Odds, SportmonksPrediction
from app.ingestion.leakage import ensure_not_leaked


def upsert_league(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, League, values, conflict_columns=["id"])


def upsert_team(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, Team, values, conflict_columns=["id"])


def upsert_season(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, Season, values, conflict_columns=["id"])


def upsert_fixture(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, Fixture, values, conflict_columns=["id"])


def upsert_match_statistics(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, MatchStatistics, values, conflict_columns=["fixture_id", "team_id"])


def upsert_match_xg(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, MatchXG, values, conflict_columns=["fixture_id", "team_id"])


def upsert_sportmonks_prediction(session: Session, values: dict[str, Any], *, kickoff: datetime) -> int:
    ensure_not_leaked(values["retrieved_at"], kickoff, label="sportmonks_predictions.retrieved_at")
    return upsert_one(session, SportmonksPrediction, values, conflict_columns=["fixture_id"])


def upsert_odds(session: Session, values: dict[str, Any], *, kickoff: datetime) -> int:
    ensure_not_leaked(values["retrieved_at"], kickoff, label="odds.retrieved_at")
    return upsert_one(
        session, Odds, values, conflict_columns=["fixture_id", "bookmaker", "market", "retrieved_at"]
    )
