"""Integration tests for ensemble fitting + calibration application,
against a real PostgreSQL database. Seeds model_predictions rows directly
(as Phase 5/6 would have produced) so these tests stay focused on Phase
8's own logic: fitting on validation data and applying to fixtures."""

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.predictions import ModelPrediction
from app.models.ensemble_service import (
    LoadedEnsembleConfig,
    apply_ensemble_and_calibration_for_fixtures,
    fit_ensemble_and_calibration,
)

UTC = timezone.utc
NOW = datetime.now(UTC)
BASE_DATE = datetime(2020, 1, 1, tzinfo=UTC)


def _seed_base(session):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2020"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()


def _seed_fixture_with_prediction(session, fixture_id, kickoff, *, poisson_prob, label):
    home_goals, away_goals = (2, 1) if label == 1 else (1, 0)
    session.add(
        Fixture(
            id=fixture_id, league_id=1, season_id=1, kickoff=kickoff, home_team_id=1, away_team_id=2,
            home_goals=home_goals, away_goals=away_goals, status="FT",
        )
    )
    session.flush()
    session.add(
        ModelPrediction(
            fixture_id=fixture_id, model_version="v1", poisson_probability=poisson_prob, predicted_at=NOW,
        )
    )
    session.flush()


def _seed_validation_set(session, n, *, seed):
    rng = random.Random(seed)
    for i in range(n):
        p = rng.uniform(0.1, 0.9)
        label = 1 if rng.random() < p else 0
        _seed_fixture_with_prediction(session, i + 1, BASE_DATE + timedelta(days=i), poisson_prob=p, label=label)


def test_fit_ensemble_and_calibration_produces_artifact(db_session, tmp_path):
    _seed_base(db_session)
    _seed_validation_set(db_session, 100, seed=1)

    result = fit_ensemble_and_calibration(
        db_session, val_start=BASE_DATE, val_end=BASE_DATE + timedelta(days=200), artifact_dir=tmp_path
    )

    assert result.val_size == 100
    assert result.ensemble_weights["poisson_probability"] > 0.0
    assert result.ensemble_weights["ml_probability"] == 0.0  # never populated -> never weighted
    assert (tmp_path / "v1.json").exists()


def test_fit_raises_when_no_validation_data(db_session, tmp_path):
    _seed_base(db_session)
    with pytest.raises(ValueError):
        fit_ensemble_and_calibration(
            db_session, val_start=BASE_DATE, val_end=BASE_DATE + timedelta(days=10), artifact_dir=tmp_path
        )


def test_loaded_config_raises_clearly_when_unfitted(tmp_path):
    with pytest.raises(FileNotFoundError):
        LoadedEnsembleConfig(tmp_path, "v1")


def test_apply_writes_final_probability_and_preserves_poisson(db_session, tmp_path):
    _seed_base(db_session)
    _seed_validation_set(db_session, 100, seed=2)
    fit_ensemble_and_calibration(
        db_session, val_start=BASE_DATE, val_end=BASE_DATE + timedelta(days=200), artifact_dir=tmp_path
    )

    target = Fixture(
        id=9999, league_id=1, season_id=1, kickoff=BASE_DATE + timedelta(days=300),
        home_team_id=1, away_team_id=2, status="NS",
    )
    db_session.add(target)
    db_session.flush()
    db_session.add(ModelPrediction(fixture_id=9999, model_version="v1", poisson_probability=0.62, predicted_at=NOW))
    db_session.flush()

    summary = apply_ensemble_and_calibration_for_fixtures(db_session, [target], artifact_dir=tmp_path, commit=False)
    db_session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1
    assert summary.failed == 0

    row = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == 9999)).scalar_one()
    assert row.poisson_probability == 0.62  # untouched by the ensemble upsert
    assert row.raw_ensemble_probability is not None
    assert 0.0 <= row.final_probability <= 1.0
    assert row.calibration_method in ("platt", "isotonic", "none")
    assert row.ensemble_weights["poisson_probability"] > 0.0


def test_apply_skips_fixture_without_stored_prediction(db_session, tmp_path):
    _seed_base(db_session)
    _seed_validation_set(db_session, 100, seed=3)
    fit_ensemble_and_calibration(
        db_session, val_start=BASE_DATE, val_end=BASE_DATE + timedelta(days=200), artifact_dir=tmp_path
    )

    bare = Fixture(
        id=8888, league_id=1, season_id=1, kickoff=BASE_DATE + timedelta(days=300),
        home_team_id=1, away_team_id=2, status="NS",
    )
    db_session.add(bare)
    db_session.flush()

    summary = apply_ensemble_and_calibration_for_fixtures(db_session, [bare], artifact_dir=tmp_path, commit=False)
    assert summary.fetched == 1
    assert summary.upserted == 0
    assert summary.failed == 1


def test_edge_is_computed_from_final_probability_once_market_data_present(db_session, tmp_path):
    """Sanity check that Phase 8's final_probability lands in the same
    generated-edge pipeline Phase 2 built - not a new assertion about
    Phase 8 itself, but proof the pieces fit together."""
    _seed_base(db_session)
    _seed_validation_set(db_session, 100, seed=4)
    fit_ensemble_and_calibration(
        db_session, val_start=BASE_DATE, val_end=BASE_DATE + timedelta(days=200), artifact_dir=tmp_path
    )
    target = Fixture(
        id=7777, league_id=1, season_id=1, kickoff=BASE_DATE + timedelta(days=300),
        home_team_id=1, away_team_id=2, status="NS",
    )
    db_session.add(target)
    db_session.flush()
    db_session.add(ModelPrediction(fixture_id=7777, model_version="v1", poisson_probability=0.7, predicted_at=NOW))
    db_session.flush()

    apply_ensemble_and_calibration_for_fixtures(db_session, [target], artifact_dir=tmp_path, commit=False)
    db_session.flush()

    row = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == 7777)).scalar_one()
    row.market_probability = 0.55
    db_session.flush()
    db_session.refresh(row)
    assert row.edge == pytest.approx(row.final_probability - 0.55)
