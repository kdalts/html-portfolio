"""Pure classifier-quality and calibration metrics for backtesting. No
I/O: every function takes plain lists of y_true (0/1 ints) and y_prob
(floats in [0,1]) and returns a float, or None when undefined (zero
samples, or only one class present) - never a misleading fabricated
number.
"""

from __future__ import annotations

from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.backtest.probability_bands import assign_band
from app.db.models.evaluation import PROBABILITY_BANDS

DEFAULT_DECISION_THRESHOLD = 0.5
DEFAULT_HIT_RATE_CONFIDENCE_THRESHOLD = 0.70


def _binary_predictions(y_prob, threshold: float) -> list[int]:
    return [1 if p >= threshold else 0 for p in y_prob]


def compute_log_loss(y_true, y_prob) -> float | None:
    if not y_true or len(set(y_true)) < 2:
        return None
    return float(log_loss(y_true, y_prob, labels=[0, 1]))


def compute_brier_score(y_true, y_prob) -> float | None:
    if not y_true:
        return None
    return float(brier_score_loss(y_true, y_prob))


def compute_roc_auc(y_true, y_prob) -> float | None:
    if not y_true or len(set(y_true)) < 2:
        return None
    return float(roc_auc_score(y_true, y_prob))


def compute_accuracy(y_true, y_prob, *, threshold: float = DEFAULT_DECISION_THRESHOLD) -> float | None:
    if not y_true:
        return None
    return float(accuracy_score(y_true, _binary_predictions(y_prob, threshold)))


def compute_precision(y_true, y_prob, *, threshold: float = DEFAULT_DECISION_THRESHOLD) -> float | None:
    if not y_true:
        return None
    return float(precision_score(y_true, _binary_predictions(y_prob, threshold), zero_division=0))


def compute_recall(y_true, y_prob, *, threshold: float = DEFAULT_DECISION_THRESHOLD) -> float | None:
    if not y_true:
        return None
    return float(recall_score(y_true, _binary_predictions(y_prob, threshold), zero_division=0))


def compute_hit_rate(
    y_true, y_prob, *, confidence_threshold: float = DEFAULT_HIT_RATE_CONFIDENCE_THRESHOLD
) -> float | None:
    """Of the fixtures where the model was CONFIDENT (predicted
    probability >= confidence_threshold), what fraction actually went
    Over 2.5? Distinct from `precision` (which uses the 0.5 decision
    threshold): this answers "when the model backs a selection with real
    conviction, how often is it right" - the practically relevant
    question for a system that only ever surfaces high-confidence picks
    (Phase 11's Top 10). None (not 0.0) when nothing met the threshold —
    "no selections" is not the same claim as "0% hit rate"."""
    selected = [actual for actual, prob in zip(y_true, y_prob) if prob >= confidence_threshold]
    if not selected:
        return None
    return sum(selected) / len(selected)


def compute_probability_band_breakdown(y_true, y_prob) -> list[dict]:
    """Per spec: for every probability band, predicted probability
    (mean), actual frequency, and sample size — the core calibration
    diagnostic. Only fixtures with predicted probability >= 0.5 are
    banded; bands with zero samples are simply omitted."""
    buckets: dict[str, list[tuple[float, int]]] = {band: [] for band in PROBABILITY_BANDS}
    for actual, prob in zip(y_true, y_prob):
        band = assign_band(prob)
        if band is not None:
            buckets[band].append((prob, actual))

    breakdown = []
    for band in PROBABILITY_BANDS:
        entries = buckets[band]
        if not entries:
            continue
        probs = [p for p, _ in entries]
        actuals = [a for _, a in entries]
        breakdown.append(
            {
                "band": band,
                "predicted_probability_mean": sum(probs) / len(probs),
                "actual_frequency": sum(actuals) / len(actuals),
                "sample_size": len(entries),
            }
        )
    return breakdown


def compute_calibration_error(y_true, y_prob) -> float | None:
    """Sample-size-weighted mean absolute gap between predicted
    probability and actual frequency across probability bands (a binned
    calibration error restricted to the >=50% range this platform
    actually selects from — a version of Expected Calibration Error)."""
    breakdown = compute_probability_band_breakdown(y_true, y_prob)
    if not breakdown:
        return None
    total = sum(b["sample_size"] for b in breakdown)
    weighted = sum(
        abs(b["predicted_probability_mean"] - b["actual_frequency"]) * b["sample_size"] for b in breakdown
    )
    return weighted / total


def compute_all_metrics(y_true, y_prob) -> dict:
    """Bundles every backtest_results metric column for one segment."""
    return {
        "sample_size": len(y_true),
        "log_loss": compute_log_loss(y_true, y_prob),
        "brier_score": compute_brier_score(y_true, y_prob),
        "roc_auc": compute_roc_auc(y_true, y_prob),
        "accuracy": compute_accuracy(y_true, y_prob),
        "precision_score": compute_precision(y_true, y_prob),
        "recall_score": compute_recall(y_true, y_prob),
        "calibration_error": compute_calibration_error(y_true, y_prob),
        "hit_rate": compute_hit_rate(y_true, y_prob),
        "predicted_probability_mean": (sum(y_prob) / len(y_prob)) if y_prob else None,
        "actual_frequency": (sum(y_true) / len(y_true)) if y_true else None,
    }
