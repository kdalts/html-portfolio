"""Idempotent upsert for league_model_performance, built on the shared
app.common.upsert.upsert_one. daily_rankings is written directly by
daily_ranking_service (delete-then-insert per ranking_date — see that
module's docstring for why an upsert doesn't fit there)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.common.upsert import upsert_one
from app.db.models.evaluation import LeagueModelPerformance


def upsert_league_model_performance(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(
        session, LeagueModelPerformance, values, conflict_columns=["league_id", "model_type", "evaluation_window_end"]
    )
