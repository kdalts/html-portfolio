"""Idempotent upsert for backtest_results, built on the shared
app.common.upsert.upsert_one."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.common.upsert import upsert_one
from app.db.models.evaluation import BacktestResult


def upsert_backtest_result(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(
        session, BacktestResult, values, conflict_columns=["backtest_run_id", "model_type", "segment_type", "segment_value"]
    )
