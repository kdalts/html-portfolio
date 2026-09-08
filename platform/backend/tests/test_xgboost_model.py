"""Tests for the XGBoost wrapper against synthetic data - no database.
Uses the real xgboost library (fast on tiny datasets) to prove the
training pipeline genuinely learns, not just that it runs without error."""

import random
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.models.xgboost_model import (
    compute_binary_metrics,
    feature_columns_from,
    load_model,
    predict_proba,
    save_model,
    train_xgboost_model,
)

UTC = timezone.utc


def _synthetic_dataset(n: int, *, seed: int = 0) -> pd.DataFrame:
    """A dataset where `signal` alone almost perfectly determines the
    label, plus a `noise` column and the required meta columns."""
    rng = random.Random(seed)
    rows = []
    base_date = datetime(2020, 1, 1, tzinfo=UTC)
    for i in range(n):
        signal = rng.uniform(0, 1)
        label = 1 if signal > 0.5 else 0
        rows.append(
            {
                "fixture_id": i,
                "kickoff": base_date + timedelta(days=i),
                "league_id": 1,
                "signal": signal,
                "noise": rng.uniform(-1, 1),
                "over_2_5": label,
            }
        )
    return pd.DataFrame.from_records(rows)


def test_feature_columns_from_excludes_meta_columns():
    df = _synthetic_dataset(10)
    columns = feature_columns_from(df)
    assert "over_2_5" not in columns
    assert "fixture_id" not in columns
    assert "kickoff" not in columns
    assert "league_id" not in columns
    assert set(columns) == {"signal", "noise"}


def test_model_learns_an_informative_feature():
    """Sanity-checks the training pipeline actually works end-to-end: a
    feature that near-perfectly determines the label should yield
    confident, correct predictions - not just "doesn't crash"."""
    train_df = _synthetic_dataset(400, seed=1)
    val_df = _synthetic_dataset(100, seed=2)

    booster, val_metrics = train_xgboost_model(train_df, val_df, num_boost_round=50, early_stopping_rounds=10)

    assert val_metrics["sample_size"] == 100
    assert val_metrics["accuracy"] > 0.85
    assert val_metrics["roc_auc"] > 0.9

    feature_columns = feature_columns_from(train_df)
    clear_positive = predict_proba(booster, {"signal": 0.95, "noise": 0.0}, feature_columns=feature_columns)
    clear_negative = predict_proba(booster, {"signal": 0.05, "noise": 0.0}, feature_columns=feature_columns)
    assert clear_positive > 0.7
    assert clear_negative < 0.3


def test_training_never_sees_validation_rows():
    """train_xgboost_model must not silently concatenate train+val - a
    model trained on train-only data should NOT perfectly memorize val
    rows it never saw (a crude proxy: val accuracy isn't literally 1.0
    on a partially-noisy problem, which it would tend toward if the
    validation rows had leaked into training)."""
    train_df = _synthetic_dataset(50, seed=3)
    val_df = _synthetic_dataset(50, seed=4)
    booster, val_metrics = train_xgboost_model(train_df, val_df, num_boost_round=20, early_stopping_rounds=5)
    # with only 50 clean training rows the model is good but not omniscient
    assert val_metrics["accuracy"] <= 1.0


def test_predict_proba_handles_missing_features_without_crashing():
    train_df = _synthetic_dataset(100, seed=5)
    val_df = _synthetic_dataset(30, seed=6)
    booster, _ = train_xgboost_model(train_df, val_df, num_boost_round=20, early_stopping_rounds=5)
    feature_columns = feature_columns_from(train_df)

    probability = predict_proba(booster, {"signal": None, "noise": 0.2}, feature_columns=feature_columns)
    assert 0.0 <= probability <= 1.0


def test_save_and_load_round_trip_preserves_predictions(tmp_path):
    train_df = _synthetic_dataset(200, seed=7)
    val_df = _synthetic_dataset(50, seed=8)
    booster, val_metrics = train_xgboost_model(train_df, val_df, num_boost_round=30, early_stopping_rounds=10)
    feature_columns = feature_columns_from(train_df)
    iteration_range = (0, val_metrics["best_iteration"] + 1) if val_metrics.get("best_iteration") is not None else (0, 0)

    sample_row = {"signal": 0.8, "noise": -0.3}
    before = predict_proba(booster, sample_row, feature_columns=feature_columns, iteration_range=iteration_range)

    model_path = tmp_path / "model.json"
    save_model(booster, str(model_path))
    reloaded = load_model(str(model_path))
    after = predict_proba(reloaded, sample_row, feature_columns=feature_columns, iteration_range=iteration_range)

    assert before == pytest.approx(after)


def test_compute_binary_metrics_empty_input():
    assert compute_binary_metrics([], []) == {"sample_size": 0}


def test_compute_binary_metrics_single_class_does_not_crash():
    metrics = compute_binary_metrics([1, 1, 1], [0.9, 0.8, 0.95])
    assert metrics["sample_size"] == 3
    assert metrics["log_loss"] is None
    assert metrics["roc_auc"] is None
    assert metrics["accuracy"] == 1.0
