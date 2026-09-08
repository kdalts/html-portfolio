"""Integrates Sportmonks' own Over 2.5 prediction into the unified
model_predictions row.

The actual retrieval + leakage-guarded storage of Sportmonks' prediction
already happened in Phase 3
(app.ingestion.service.ingest_prediction_for_fixture writes to
sportmonks_predictions, enforcing retrieved_at < kickoff). This module's
job is narrower: sync an already-ingested sportmonks_predictions row's
over_2_5_probability onto model_predictions.sportmonks_probability, so
Phase 8's ensemble can see it. No new leakage exposure here — a row only
exists in sportmonks_predictions at all because it already passed the
guard at ingestion time.

Sportmonks model-performance information (spec: "Also store Sportmonks
model-performance information where available") isn't exposed by a known,
separate Sportmonks endpoint as of this build (no live token was
available to verify) — the raw prediction payload, including whatever
extra fields Sportmonks includes, is already fully preserved in
sportmonks_predictions.raw_payload (Phase 3), so nothing here is lost;
there's simply nothing further to normalize into its own column without
confirming a real payload shape.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.batch import BatchSummary
from app.db.models.fixtures import Fixture
from app.db.models.match_data import SportmonksPrediction
from app.db.models.predictions import ModelPrediction
from app.models import repository
from app.models.constants import DEFAULT_MODEL_VERSION

logger = logging.getLogger(__name__)


def sync_sportmonks_prediction_for_fixture(
    session: Session, fixture: Fixture, *, model_version: str = DEFAULT_MODEL_VERSION
) -> dict | None:
    sportmonks_row = session.execute(
        select(SportmonksPrediction).where(SportmonksPrediction.fixture_id == fixture.id)
    ).scalar_one_or_none()
    if sportmonks_row is None or sportmonks_row.over_2_5_probability is None:
        return None

    existing = session.execute(
        select(ModelPrediction).where(
            ModelPrediction.fixture_id == fixture.id, ModelPrediction.model_version == model_version
        )
    ).scalar_one_or_none()
    # Carried forward when the row already exists (see Phase 8's fix):
    # Postgres validates NOT NULL columns against the proposed INSERT row
    # even when ON CONFLICT DO UPDATE ends up running instead.
    predicted_at = existing.predicted_at if existing is not None else datetime.now(timezone.utc)

    return {
        "fixture_id": fixture.id,
        "model_version": model_version,
        "sportmonks_probability": sportmonks_row.over_2_5_probability,
        "predicted_at": predicted_at,
    }


def sync_and_store_sportmonks_predictions(
    session: Session,
    fixtures: list[Fixture],
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    commit: bool = True,
) -> BatchSummary:
    summary = BatchSummary()
    for fixture in fixtures:
        summary.fetched += 1
        try:
            with session.begin_nested():
                values = sync_sportmonks_prediction_for_fixture(session, fixture, model_version=model_version)
                if values is None:
                    raise ValueError("no ingested Sportmonks prediction available for this fixture")
                repository.upsert_model_prediction(session, values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(fixture.id, exc)
            logger.warning("Failed to sync Sportmonks prediction for fixture %s: %s", fixture.id, exc)

    if commit:
        session.commit()
    return summary
