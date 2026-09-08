"""Integration tests for the ML training/prediction service: real
PostgreSQL + a real (small) XGBoost training run, with model artifacts
written to a pytest tmp_path so nothing touches the real artifacts/ dir."""

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.predictions import ModelPrediction
from app.models.ml_service import (
    LoadedArtifact,
    compute_and_store_ml_predictions,
    train_and_save_model,
)

UTC = timezone.utc
NOW = datetime.now(UTC)
BASE_DATE = datetime(2020, 1, 1, tzinfo=UTC)


def _seed_league(session):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2019/2020"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()


def _seed_fixture_with_features(session, fixture_id, kickoff, *, signal, label=None, status="FT"):
    home_goals = away_goals = None
    if label is not None:
        home_goals, away_goals = (2, 1) if label == 1 else (1, 0)
    session.add(
        Fixture(
            id=fixture_id,
            league_id=1,
            season_id=1,
            kickoff=kickoff,
            home_team_id=1,
            away_team_id=2,
            home_goals=home_goals,
            away_goals=away_goals,
            status=status,
        )
    )
    session.flush()
    fixture = session.get(Fixture, fixture_id)
    session.add(
        TeamFeatures(
            team_id=1,
            fixture_id=fixture_id,
            is_home=True,
            as_of=kickoff,
            computed_at=NOW,
            overall_last10_goals_scored=signal,
        )
    )
    session.add(
        TeamFeatures(
            team_id=2,
            fixture_id=fixture_id,
            is_home=False,
            as_of=kickoff,
            computed_at=NOW,
            overall_last10_goals_scored=1.0 - signal,
        )
    )
    session.add(MatchFeatures(fixture_id=fixture_id, league_avg_goals=2.5, computed_at=NOW))
    session.flush()
    return fixture


def _seed_training_set(session, n, *, seed=0, start_day=0):
    rng = random.Random(seed)
    for i in range(n):
        signal = rng.uniform(0, 1)
        label = 1 if signal > 0.5 else 0
        _seed_fixture_with_features(session, start_day + i + 1, BASE_DATE + timedelta(days=start_day + i), signal=signal, label=label)


def test_train_and_save_model_produces_artifact_and_metadata(db_session, tmp_path):
    _seed_league(db_session)
    _seed_training_set(db_session, 150, seed=1)

    result = train_and_save_model(
        db_session,
        train_start=BASE_DATE,
        train_end=BASE_DATE + timedelta(days=110),
        val_end=BASE_DATE + timedelta(days=160),
        artifact_dir=tmp_path,
    )

    assert result.train_size > 0
    assert result.val_size > 0
    assert result.train_size + result.val_size == 150
    assert (tmp_path / "v1.json").exists()
    assert (tmp_path / "v1.meta.json").exists()
    assert result.val_metrics["accuracy"] > 0.7  # the synthetic signal is learnable


def test_train_raises_on_empty_window(db_session, tmp_path):
    _seed_league(db_session)
    with pytest.raises(ValueError):
        train_and_save_model(
            db_session,
            train_start=BASE_DATE,
            train_end=BASE_DATE + timedelta(days=10),
            val_end=BASE_DATE + timedelta(days=20),
            artifact_dir=tmp_path,
        )


def test_loaded_artifact_raises_clearly_when_untrained(tmp_path):
    with pytest.raises(FileNotFoundError):
        LoadedArtifact(tmp_path, "v1")


def test_predict_after_training_stores_ml_probability(db_session, tmp_path):
    _seed_league(db_session)
    _seed_training_set(db_session, 150, seed=2)
    train_and_save_model(
        db_session,
        train_start=BASE_DATE,
        train_end=BASE_DATE + timedelta(days=110),
        val_end=BASE_DATE + timedelta(days=160),
        artifact_dir=tmp_path,
    )

    target = _seed_fixture_with_features(
        db_session, 9999, BASE_DATE + timedelta(days=200), signal=0.9, status="NS"
    )

    summary = compute_and_store_ml_predictions(db_session, [target], artifact_dir=tmp_path, commit=False)
    db_session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1
    assert summary.failed == 0

    row = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == 9999)).scalar_one()
    assert 0.0 <= row.ml_probability <= 1.0
    assert row.model_version == "v1"


def test_predict_merges_with_existing_poisson_row(db_session, tmp_path):
    _seed_league(db_session)
    _seed_training_set(db_session, 150, seed=3)
    train_and_save_model(
        db_session,
        train_start=BASE_DATE,
        train_end=BASE_DATE + timedelta(days=110),
        val_end=BASE_DATE + timedelta(days=160),
        artifact_dir=tmp_path,
    )
    target = _seed_fixture_with_features(
        db_session, 9999, BASE_DATE + timedelta(days=200), signal=0.9, status="NS"
    )
    db_session.add(
        ModelPrediction(fixture_id=9999, model_version="v1", poisson_probability=0.42, predicted_at=NOW)
    )
    db_session.flush()

    compute_and_store_ml_predictions(db_session, [target], artifact_dir=tmp_path, commit=False)
    db_session.flush()

    rows = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == 9999)).scalars().all()
    assert len(rows) == 1
    assert rows[0].poisson_probability == 0.42  # untouched
    assert rows[0].ml_probability is not None  # now also populated


def test_predict_skips_fixture_missing_features(db_session, tmp_path):
    _seed_league(db_session)
    _seed_training_set(db_session, 150, seed=4)
    train_and_save_model(
        db_session,
        train_start=BASE_DATE,
        train_end=BASE_DATE + timedelta(days=110),
        val_end=BASE_DATE + timedelta(days=160),
        artifact_dir=tmp_path,
    )

    bare_fixture = Fixture(
        id=9998,
        league_id=1,
        season_id=1,
        kickoff=BASE_DATE + timedelta(days=201),
        home_team_id=1,
        away_team_id=2,
        status="NS",
    )
    db_session.add(bare_fixture)
    db_session.flush()

    summary = compute_and_store_ml_predictions(db_session, [bare_fixture], artifact_dir=tmp_path, commit=False)
    assert summary.fetched == 1
    assert summary.upserted == 0
    assert summary.failed == 1
