"""Orchestrates XGBoost training and prediction for Over 2.5.

Chronological splitting only: `build_training_matrix` pulls fixtures
ordered by kickoff, `chronological_split` partitions by kickoff cutoffs
(never randomly shuffled), and training only ever sees the train
partition — the validation partition is used solely for early stopping /
reporting, never gradient updates, and the held-out test evaluation
belongs to Phase 7's backtesting, not here.

The trained model is a filesystem artifact (native XGBoost JSON plus a
metadata sidecar recording the exact feature-column order, training
window, and validation metrics) rather than a database row — there is no
"trained model" table in the required schema, and a self-describing
artifact on disk is standard practice for this. As with the Poisson
model, no leakage guard applies to `predicted_at`: the only inputs are
Phase 4 features, already leakage-safe by construction, and training data
is chronologically partitioned so the model never learns from a
post-cutoff row.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.common.batch import BatchSummary
from app.db.models.fixtures import Fixture
from app.models import repository
from app.models.chronological_split import chronological_split
from app.models.constants import DEFAULT_MODEL_VERSION
from app.models.dataset import build_feature_row_for_fixture, build_training_matrix
from app.models.xgboost_model import feature_columns_from, load_model, predict_proba, save_model, train_xgboost_model

logger = logging.getLogger(__name__)

DEFAULT_ARTIFACT_DIR = Path(__file__).resolve().parent.parent.parent / "artifacts" / "xgboost"


@dataclass
class TrainingResult:
    model_version: str
    train_start: str
    train_end: str
    val_end: str
    train_size: int
    val_size: int
    feature_columns: list[str]
    val_metrics: dict
    model_path: str
    metadata_path: str


def _artifact_paths(artifact_dir: Path, model_version: str) -> tuple[Path, Path]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir / f"{model_version}.json", artifact_dir / f"{model_version}.meta.json"


def train_and_save_model(
    session: Session,
    *,
    train_start: datetime,
    train_end: datetime,
    val_end: datetime,
    model_version: str = DEFAULT_MODEL_VERSION,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
) -> TrainingResult:
    full_df = build_training_matrix(session, start_date=train_start, end_date=val_end)
    if full_df.empty:
        raise ValueError("no fixtures with computed features and a known result in the requested window")

    train_df, val_df, _future = chronological_split(full_df, train_end=train_end, val_end=val_end)
    if train_df.empty:
        raise ValueError("training partition is empty - check train_start/train_end")

    feature_columns = feature_columns_from(full_df)
    booster, val_metrics = train_xgboost_model(train_df, val_df, feature_columns=feature_columns)

    model_path, metadata_path = _artifact_paths(Path(artifact_dir), model_version)
    save_model(booster, str(model_path))

    metadata = {
        "model_version": model_version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_start": train_start.isoformat(),
        "train_end": train_end.isoformat(),
        "val_end": val_end.isoformat(),
        "train_size": len(train_df),
        "val_size": len(val_df),
        "feature_columns": feature_columns,
        "val_metrics": val_metrics,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str))

    return TrainingResult(
        model_version=model_version,
        train_start=train_start.isoformat(),
        train_end=train_end.isoformat(),
        val_end=val_end.isoformat(),
        train_size=len(train_df),
        val_size=len(val_df),
        feature_columns=feature_columns,
        val_metrics=val_metrics,
        model_path=str(model_path),
        metadata_path=str(metadata_path),
    )


class LoadedArtifact:
    """Loads a trained model + its metadata once, for reuse across a
    whole batch of predictions."""

    def __init__(self, artifact_dir: Path, model_version: str):
        model_path, metadata_path = _artifact_paths(Path(artifact_dir), model_version)
        if not model_path.exists() or not metadata_path.exists():
            raise FileNotFoundError(
                f"no trained model artifact for model_version={model_version!r} at {artifact_dir} "
                "- run training first (python -m app.models.ml_cli train)"
            )
        self.booster = load_model(str(model_path))
        metadata = json.loads(metadata_path.read_text())
        self.feature_columns: list[str] = metadata["feature_columns"]
        best_iteration = (metadata.get("val_metrics") or {}).get("best_iteration")
        self.iteration_range: tuple[int, int] = (0, best_iteration + 1) if best_iteration is not None else (0, 0)


def compute_ml_prediction_for_fixture(
    session: Session,
    fixture: Fixture,
    artifact: LoadedArtifact,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> dict | None:
    feature_row = build_feature_row_for_fixture(session, fixture)
    if feature_row is None:
        return None
    probability = predict_proba(
        artifact.booster,
        feature_row,
        feature_columns=artifact.feature_columns,
        iteration_range=artifact.iteration_range,
    )
    return {
        "fixture_id": fixture.id,
        "model_version": model_version,
        "ml_probability": probability,
        "predicted_at": datetime.now(timezone.utc),
    }


def compute_and_store_ml_predictions(
    session: Session,
    fixtures: list[Fixture],
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    artifact_dir: Path = DEFAULT_ARTIFACT_DIR,
    commit: bool = True,
) -> BatchSummary:
    summary = BatchSummary()
    artifact = LoadedArtifact(Path(artifact_dir), model_version)  # raises loudly if untrained

    for fixture in fixtures:
        summary.fetched += 1
        try:
            with session.begin_nested():
                values = compute_ml_prediction_for_fixture(session, fixture, artifact, model_version=model_version)
                if values is None:
                    raise ValueError("features not computed yet for this fixture")
                repository.upsert_model_prediction(session, values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(fixture.id, exc)
            logger.warning("Failed to compute ML prediction for fixture %s: %s", fixture.id, exc)

    if commit:
        session.commit()
    return summary
