"""Walk-forward backtesting: expanding-window folds per spec's example
(train 2019-2022 -> test 2023, train 2019-2023 -> test 2024, train
2019-2024 -> test 2025). Each fold evaluates every configured model_type
on that fold's held-out test fixtures and writes per-segment metrics to
backtest_results.

For 'ml', each fold trains its OWN model artifact using ONLY that fold's
training window (an internal tail slice of the training window serves as
the early-stopping validation set) — a fold's test predictions must never
come from a model that has seen any data past that fold's train_end, or
the walk-forward evaluation would itself leak future information into a
"historical" result. 'poisson' has no learned parameters beyond Phase 4's
features (already leakage-safe by construction), so it's evaluated
directly with no retraining needed per fold.

`backtest_run_id` is fold-specific (f"wf-{run_tag}-{fold.label}") so each
fold's rows satisfy backtest_results' unique constraint independently —
a single logical "walk-forward run" spans multiple backtest_run_ids, one
per fold, all sharing the same run_tag.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtest import repository
from app.backtest.segments import EvalRow, build_segment_results
from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.models.ml_service import DEFAULT_ARTIFACT_DIR, LoadedArtifact, compute_ml_prediction_for_fixture, train_and_save_model
from app.models.poisson import PoissonEstimate, estimate_poisson
from app.models.utils import row_to_dict

logger = logging.getLogger(__name__)

DEFAULT_BACKTEST_ARTIFACT_DIR = DEFAULT_ARTIFACT_DIR / "backtest"
DEFAULT_VALIDATION_FRACTION = 0.15
SUPPORTED_MODEL_TYPES = ("poisson", "ml")


@dataclass(frozen=True)
class WalkForwardFold:
    train_start: datetime
    train_end: datetime  # == test_start
    test_end: datetime
    label: str


def default_folds() -> list[WalkForwardFold]:
    tz = timezone.utc
    start = datetime(2019, 1, 1, tzinfo=tz)
    return [
        WalkForwardFold(start, datetime(2023, 1, 1, tzinfo=tz), datetime(2024, 1, 1, tzinfo=tz), "2023"),
        WalkForwardFold(start, datetime(2024, 1, 1, tzinfo=tz), datetime(2025, 1, 1, tzinfo=tz), "2024"),
        WalkForwardFold(start, datetime(2025, 1, 1, tzinfo=tz), datetime(2026, 1, 1, tzinfo=tz), "2025"),
    ]


def _fold_test_fixtures(session: Session, fold: WalkForwardFold) -> list[Fixture]:
    return list(
        session.execute(
            select(Fixture)
            .where(Fixture.kickoff >= fold.train_end, Fixture.kickoff < fold.test_end, Fixture.over_2_5.isnot(None))
            .order_by(Fixture.kickoff)
        )
        .scalars()
        .all()
    )


def _poisson_estimate_for_fixture(session: Session, fixture: Fixture) -> PoissonEstimate | None:
    home_features = session.execute(
        select(TeamFeatures).where(TeamFeatures.fixture_id == fixture.id, TeamFeatures.team_id == fixture.home_team_id)
    ).scalar_one_or_none()
    away_features = session.execute(
        select(TeamFeatures).where(TeamFeatures.fixture_id == fixture.id, TeamFeatures.team_id == fixture.away_team_id)
    ).scalar_one_or_none()
    match_features = session.execute(
        select(MatchFeatures).where(MatchFeatures.fixture_id == fixture.id)
    ).scalar_one_or_none()
    if home_features is None or away_features is None or match_features is None:
        return None
    return estimate_poisson(row_to_dict(home_features), row_to_dict(away_features), row_to_dict(match_features))


def _build_eval_rows(
    session: Session, fixtures: list[Fixture], *, model_type: str, ml_artifact: LoadedArtifact | None
) -> list[EvalRow]:
    rows = []
    for fixture in fixtures:
        poisson_estimate = _poisson_estimate_for_fixture(session, fixture)
        home_leaning = (
            poisson_estimate.expected_home_goals >= poisson_estimate.expected_away_goals
            if poisson_estimate is not None
            else None
        )

        if model_type == "poisson":
            if poisson_estimate is None:
                continue
            y_prob = poisson_estimate.probability_over_2_5
        elif model_type == "ml":
            if ml_artifact is None:
                continue
            prediction = compute_ml_prediction_for_fixture(session, fixture, ml_artifact, model_version="unused")
            if prediction is None:
                continue
            y_prob = prediction["ml_probability"]
        else:
            raise ValueError(f"unsupported backtest model_type: {model_type!r}")

        rows.append(
            EvalRow(
                fixture_id=fixture.id,
                y_true=int(fixture.over_2_5),
                y_prob=y_prob,
                league_id=fixture.league_id,
                season_id=fixture.season_id,
                home_leaning=home_leaning,
            )
        )
    return rows


def run_walkforward_backtest(
    session: Session,
    *,
    folds: list[WalkForwardFold] | None = None,
    model_types: tuple[str, ...] = SUPPORTED_MODEL_TYPES,
    run_tag: str | None = None,
    artifact_dir: Path = DEFAULT_BACKTEST_ARTIFACT_DIR,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    commit: bool = True,
) -> list[str]:
    """Returns the backtest_run_ids written (one per fold)."""
    folds = folds or default_folds()
    run_tag = run_tag or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    run_ids: list[str] = []

    for fold in folds:
        backtest_run_id = f"wf-{run_tag}-{fold.label}"
        run_ids.append(backtest_run_id)
        test_fixtures = _fold_test_fixtures(session, fold)

        ml_artifact: LoadedArtifact | None = None
        if "ml" in model_types and test_fixtures:
            internal_val_start = fold.train_start + (fold.train_end - fold.train_start) * (1 - validation_fraction)
            try:
                train_and_save_model(
                    session,
                    train_start=fold.train_start,
                    train_end=internal_val_start,
                    val_end=fold.train_end,
                    model_version=f"backtest-{fold.label}",
                    artifact_dir=artifact_dir,
                )
                ml_artifact = LoadedArtifact(artifact_dir, f"backtest-{fold.label}")
            except (ValueError, FileNotFoundError) as exc:
                logger.warning("Skipping ML backtest for fold %s: %s", fold.label, exc)

        for model_type in model_types:
            eval_rows = _build_eval_rows(
                session, test_fixtures, model_type=model_type, ml_artifact=ml_artifact if model_type == "ml" else None
            )
            for result in build_segment_results(eval_rows):
                values = {
                    "backtest_run_id": backtest_run_id,
                    "train_start_date": fold.train_start.date(),
                    "train_end_date": fold.train_end.date(),
                    "test_start_date": fold.train_end.date(),
                    "test_end_date": fold.test_end.date(),
                    "model_type": model_type,
                    **result,
                }
                try:
                    with session.begin_nested():
                        repository.upsert_backtest_result(session, values)
                except Exception as exc:  # noqa: BLE001 - isolate and record, keep the run going
                    logger.warning(
                        "Failed to write backtest_results row (%s/%s/%s/%s): %s",
                        backtest_run_id,
                        model_type,
                        result.get("segment_type"),
                        result.get("segment_value"),
                        exc,
                    )

        if commit:
            session.commit()

    return run_ids
