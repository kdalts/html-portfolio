"""XGBoost binary classifier for Over 2.5, wrapped as a small, DB-free
module: given already-assembled DataFrames (see dataset.py), train,
evaluate, predict, and serialize a model. No knowledge of the database or
Sportmonks here - only numeric feature matrices in, probabilities out.

Missing feature values (None/NaN — expected in practice: box-score
stats/xG are unpopulated until Phase 3's placeholder type IDs are
configured, and early-season rolling windows are naturally incomplete)
are passed straight to XGBoost's native missing-value handling rather
than imputed: the booster learns a default split direction for each
split point, which is a better-founded way to handle "genuinely unknown"
than inventing a substitute value.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score, log_loss, roc_auc_score

from app.models.dataset import META_COLUMNS

DEFAULT_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "max_depth": 4,
    "eta": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "seed": 42,
}
DEFAULT_NUM_BOOST_ROUND = 500
DEFAULT_EARLY_STOPPING_ROUNDS = 30


def feature_columns_from(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META_COLUMNS]


def _to_dmatrix(df: pd.DataFrame, feature_columns: list[str], *, label_column: str | None) -> xgb.DMatrix:
    X = df[feature_columns].astype(float)
    label = df[label_column].astype(float) if label_column and label_column in df.columns else None
    return xgb.DMatrix(X, label=label, feature_names=list(feature_columns), missing=np.nan)


def _iteration_range(booster: xgb.Booster) -> tuple[int, int]:
    best_iteration = getattr(booster, "best_iteration", None)
    return (0, best_iteration + 1) if best_iteration is not None else (0, 0)  # (0, 0) = use all trees


def compute_binary_metrics(y_true, y_prob) -> dict:
    y_true = list(y_true)
    y_prob = list(y_prob)
    metrics: dict = {"sample_size": len(y_true)}
    if not y_true:
        return metrics

    y_pred = [1 if p >= 0.5 else 0 for p in y_prob]
    metrics["accuracy"] = accuracy_score(y_true, y_pred)
    if len(set(y_true)) > 1:
        metrics["log_loss"] = log_loss(y_true, y_prob, labels=[0, 1])
        metrics["roc_auc"] = roc_auc_score(y_true, y_prob)
    else:
        metrics["log_loss"] = None
        metrics["roc_auc"] = None
    return metrics


def train_xgboost_model(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    *,
    feature_columns: list[str] | None = None,
    params: dict | None = None,
    num_boost_round: int = DEFAULT_NUM_BOOST_ROUND,
    early_stopping_rounds: int = DEFAULT_EARLY_STOPPING_ROUNDS,
) -> tuple[xgb.Booster, dict]:
    """Trains only on train_df. val_df (if non-empty) is used solely for
    early stopping and reporting - never for gradient updates. Returns
    (booster, val_metrics), with val_metrics["best_iteration"] recorded so
    callers can persist it for correct prediction after a reload."""
    feature_columns = feature_columns or feature_columns_from(train_df)
    dtrain = _to_dmatrix(train_df, feature_columns, label_column="over_2_5")
    dval = _to_dmatrix(val_df, feature_columns, label_column="over_2_5") if len(val_df) else None

    evals = [(dtrain, "train")]
    if dval is not None:
        evals.append((dval, "validation"))

    booster = xgb.train(
        {**DEFAULT_PARAMS, **(params or {})},
        dtrain,
        num_boost_round=num_boost_round,
        evals=evals,
        early_stopping_rounds=early_stopping_rounds if dval is not None else None,
        verbose_eval=False,
    )

    iteration_range = _iteration_range(booster)
    val_metrics: dict = {"best_iteration": getattr(booster, "best_iteration", None)}
    if dval is not None and len(val_df):
        val_probs = booster.predict(dval, iteration_range=iteration_range)
        val_metrics.update(compute_binary_metrics(val_df["over_2_5"], val_probs))

    return booster, val_metrics


def predict_proba(
    booster: xgb.Booster,
    feature_row: dict,
    *,
    feature_columns: list[str],
    iteration_range: tuple[int, int] | None = None,
) -> float:
    df = pd.DataFrame([{col: feature_row.get(col) for col in feature_columns}])
    dmatrix = _to_dmatrix(df, feature_columns, label_column=None)
    preds = booster.predict(dmatrix, iteration_range=iteration_range or (0, 0))
    return float(preds[0])


def save_model(booster: xgb.Booster, path: str) -> None:
    booster.save_model(path)


def load_model(path: str) -> xgb.Booster:
    booster = xgb.Booster()
    booster.load_model(path)
    return booster
