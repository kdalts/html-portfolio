"""Orchestrates ensemble weighting + calibration: fits both on a
validation window of already-stored model_predictions rows (produced by
Phase 5/6), saves the fitted configuration as a small JSON artifact (same
"self-describing filesystem artifact" pattern as Phase 6's model — there
is no dedicated table for this config in the required schema), and
applies it to fixtures to compute raw_ensemble_probability and
final_probability.

Fitting reads existing model_predictions (does not recompute
poisson/ml itself) — ensemble/calibration are meta-level steps over
already-produced model outputs, evaluated only on fixtures with a known
result (needed to fit against labels).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.batch import BatchSummary
from app.db.models.fixtures import Fixture
from app.db.models.predictions import ModelPrediction
from app.models import repository
from app.models.calibration import apply_calibration, calibrator_from_dict, select_calibrator
from app.models.constants import DEFAULT_MODEL_VERSION
from app.models.ensemble import DEFAULT_SOURCES, compute_raw_ensemble_probability, fit_ensemble_weights

logger = logging.getLogger(__name__)

DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "ensemble"


@dataclass
class EnsembleFitResult:
    model_version: str
    val_start: str
    val_end: str
    val_size: int
    ensemble_weights: dict[str, float]
    calibration_method: str
    artifact_path: str


def _artifact_path(artifact_dir: Path, model_version: str) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir / f"{model_version}.json"


def _fetch_validation_rows(session: Session, *, val_start: datetime, val_end: datetime, model_version: str) -> list[dict]:
    rows = session.execute(
        select(ModelPrediction, Fixture.over_2_5)
        .join(Fixture, Fixture.id == ModelPrediction.fixture_id)
        .where(
            ModelPrediction.model_version == model_version,
            Fixture.kickoff >= val_start,
            Fixture.kickoff < val_end,
            Fixture.over_2_5.isnot(None),
        )
    ).all()
    return [
        {
            "poisson_probability": prediction.poisson_probability,
            "ml_probability": prediction.ml_probability,
            "sportmonks_probability": prediction.sportmonks_probability,
            "over_2_5": int(over_2_5),
        }
        for prediction, over_2_5 in rows
    ]


def fit_ensemble_and_calibration(
    session: Session,
    *,
    val_start: datetime,
    val_end: datetime,
    model_version: str = DEFAULT_MODEL_VERSION,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> EnsembleFitResult:
    validation_rows = _fetch_validation_rows(session, val_start=val_start, val_end=val_end, model_version=model_version)
    if not validation_rows:
        raise ValueError("no fixtures with a known result and stored predictions in the requested validation window")

    weights = fit_ensemble_weights(validation_rows)

    raw_probs, y_true = [], []
    for row in validation_rows:
        raw = compute_raw_ensemble_probability(row, weights)
        if raw is not None:
            raw_probs.append(raw)
            y_true.append(row["over_2_5"])

    method, calibrator = select_calibrator(raw_probs, y_true)

    artifact = {
        "model_version": model_version,
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "val_start": val_start.isoformat(),
        "val_end": val_end.isoformat(),
        "val_size": len(validation_rows),
        "ensemble_weights": weights,
        "calibration": {"method": method} if calibrator is None else calibrator.to_dict(),
    }
    artifact_path = _artifact_path(Path(artifact_dir), model_version)
    artifact_path.write_text(json.dumps(artifact, indent=2))

    return EnsembleFitResult(
        model_version=model_version,
        val_start=val_start.isoformat(),
        val_end=val_end.isoformat(),
        val_size=len(validation_rows),
        ensemble_weights=weights,
        calibration_method=method,
        artifact_path=str(artifact_path),
    )


class LoadedEnsembleConfig:
    def __init__(self, artifact_dir: Path, model_version: str):
        path = _artifact_path(Path(artifact_dir), model_version)
        if not path.exists():
            raise FileNotFoundError(
                f"no fitted ensemble/calibration config for model_version={model_version!r} at {artifact_dir} "
                "- run fitting first (python -m app.models.ensemble_cli fit)"
            )
        data = json.loads(path.read_text())
        self.weights: dict[str, float] = data["ensemble_weights"]
        self.calibration_method: str = data["calibration"]["method"]
        self.calibrator = None if self.calibration_method == "none" else calibrator_from_dict(data["calibration"])


def compute_ensemble_and_calibration_for_fixture(
    session: Session, fixture: Fixture, config: LoadedEnsembleConfig, *, model_version: str = DEFAULT_MODEL_VERSION
) -> dict | None:
    existing = session.execute(
        select(ModelPrediction).where(
            ModelPrediction.fixture_id == fixture.id, ModelPrediction.model_version == model_version
        )
    ).scalar_one_or_none()
    if existing is None:
        return None

    row = {source: getattr(existing, source) for source in DEFAULT_SOURCES}
    raw_probability = compute_raw_ensemble_probability(row, config.weights)
    if raw_probability is None:
        return None

    final_probability = apply_calibration(config.calibration_method, config.calibrator, raw_probability)

    return {
        "fixture_id": fixture.id,
        "model_version": model_version,
        # Carried forward, not refreshed: Postgres validates NOT NULL
        # columns against the proposed INSERT row even when ON CONFLICT
        # DO UPDATE ends up running instead, so predicted_at must be
        # present here even though this write only touches the
        # ensemble/calibration columns. Reusing the existing value (set
        # by whichever of Phase 5/6 ran first) also correctly avoids
        # bumping "when this fixture's prediction was generated" just
        # because a later pipeline stage added more columns to the row.
        "predicted_at": existing.predicted_at,
        "raw_ensemble_probability": raw_probability,
        "ensemble_weights": config.weights,
        "calibration_method": config.calibration_method,
        "final_probability": final_probability,
    }


def apply_ensemble_and_calibration_for_fixtures(
    session: Session,
    fixtures: list[Fixture],
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
    commit: bool = True,
) -> BatchSummary:
    summary = BatchSummary()
    config = LoadedEnsembleConfig(Path(artifact_dir), model_version)

    for fixture in fixtures:
        summary.fetched += 1
        try:
            with session.begin_nested():
                values = compute_ensemble_and_calibration_for_fixture(session, fixture, config, model_version=model_version)
                if values is None:
                    raise ValueError("no stored model_predictions row (or no usable source) for this fixture")
                repository.upsert_model_prediction(session, values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(fixture.id, exc)
            logger.warning("Failed to compute ensemble/calibration for fixture %s: %s", fixture.id, exc)

    if commit:
        session.commit()
    return summary
