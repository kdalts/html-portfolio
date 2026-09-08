"""Idempotent upsert for model_predictions, built on the shared
app.common.upsert.upsert_one.

Each phase that contributes a probability source (Poisson here, ML in
Phase 6, ensemble/calibration in Phase 7/8, Sportmonks in Phase 9) calls
this with only the columns it computed. Because upsert_one's ON CONFLICT
SET clause only touches the keys present in `values`, writing
{poisson_probability, ...} here and later writing
{ml_probability, ...} for the same (fixture_id, model_version) correctly
fills in the same row without clobbering columns another phase already
set.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.common.upsert import upsert_one
from app.db.models.predictions import ModelPrediction


def upsert_model_prediction(session: Session, values: dict[str, Any]) -> int:
    return upsert_one(session, ModelPrediction, values, conflict_columns=["fixture_id", "model_version"])
