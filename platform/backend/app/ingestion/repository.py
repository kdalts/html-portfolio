"""Idempotent upserts (INSERT ... ON CONFLICT DO UPDATE) for every table
ingestion writes to. Re-running ingestion over the same data is always
safe: rows are matched on their natural/unique key and updated in place,
never duplicated.

Generated columns (fixtures.total_goals/over_2_5, odds' implied
probabilities/market_probability, model_predictions.edge) are never part
of the value dicts these functions accept — Postgres computes them, and
attempting to set them explicitly would be rejected by the database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import MatchStatistics, MatchXG, Odds, SportmonksPrediction
from app.ingestion.leakage import ensure_not_leaked


def _upsert_one(session: Session, model, values: dict[str, Any], conflict_columns: list[str]) -> Any:
    table = model.__table__
    stmt = pg_insert(table).values(**values)
    settable = {name: stmt.excluded[name] for name in values if name not in conflict_columns}
    settable["updated_at"] = func.now()
    stmt = stmt.on_conflict_do_update(index_elements=conflict_columns, set_=settable)
    pk_columns = [c.name for c in table.primary_key.columns]
    stmt = stmt.returning(*[table.c[name] for name in pk_columns])
    result = session.execute(stmt).one()
    return result[0] if len(pk_columns) == 1 else tuple(result)


def upsert_league(session: Session, values: dict[str, Any]) -> int:
    return _upsert_one(session, League, values, conflict_columns=["id"])


def upsert_team(session: Session, values: dict[str, Any]) -> int:
    return _upsert_one(session, Team, values, conflict_columns=["id"])


def upsert_season(session: Session, values: dict[str, Any]) -> int:
    return _upsert_one(session, Season, values, conflict_columns=["id"])


def upsert_fixture(session: Session, values: dict[str, Any]) -> int:
    return _upsert_one(session, Fixture, values, conflict_columns=["id"])


def upsert_match_statistics(session: Session, values: dict[str, Any]) -> int:
    return _upsert_one(session, MatchStatistics, values, conflict_columns=["fixture_id", "team_id"])


def upsert_match_xg(session: Session, values: dict[str, Any]) -> int:
    return _upsert_one(session, MatchXG, values, conflict_columns=["fixture_id", "team_id"])


def upsert_sportmonks_prediction(session: Session, values: dict[str, Any], *, kickoff: datetime) -> int:
    ensure_not_leaked(values["retrieved_at"], kickoff, label="sportmonks_predictions.retrieved_at")
    return _upsert_one(session, SportmonksPrediction, values, conflict_columns=["fixture_id"])


def upsert_odds(session: Session, values: dict[str, Any], *, kickoff: datetime) -> int:
    ensure_not_leaked(values["retrieved_at"], kickoff, label="odds.retrieved_at")
    return _upsert_one(
        session, Odds, values, conflict_columns=["fixture_id", "bookmaker", "market", "retrieved_at"]
    )
