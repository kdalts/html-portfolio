"""Idempotent upserts for the feature-store tables, built on the shared
app.common.upsert.upsert_one (same mechanism Phase 3 ingestion uses)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.common.upsert import upsert_one
from app.db.models.features import MatchFeatures, TeamFeatures


def upsert_team_features(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, TeamFeatures, values, conflict_columns=["team_id", "fixture_id"])


def upsert_match_features(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, MatchFeatures, values, conflict_columns=["fixture_id"])
