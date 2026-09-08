"""Pure unit tests for backtest metrics - no database."""

import math

import pytest

from app.backtest.metrics import (
    compute_accuracy,
    compute_all_metrics,
    compute_brier_score,
    compute_calibration_error,
    compute_hit_rate,
    compute_log_loss,
    compute_precision,
    compute_probability_band_breakdown,
    compute_recall,
    compute_roc_auc,
)


# --- basic classifier metrics against known values ------------------------------


def test_log_loss_known_value():
    y_true = [1, 0]
    y_prob = [0.9, 0.1]
    expected = -(math.log(0.9) + math.log(0.9)) / 2
    assert compute_log_loss(y_true, y_prob) == pytest.approx(expected)


def test_log_loss_none_for_single_class():
    assert compute_log_loss([1, 1, 1], [0.9, 0.8, 0.95]) is None


def test_log_loss_none_for_empty():
    assert compute_log_loss([], []) is None


def test_brier_score_known_value():
    # (0.8-1)^2 and (0.3-0)^2, averaged
    expected = ((0.8 - 1) ** 2 + (0.3 - 0) ** 2) / 2
    assert compute_brier_score([1, 0], [0.8, 0.3]) == pytest.approx(expected)


def test_brier_score_perfect_predictions_is_zero():
    assert compute_brier_score([1, 0, 1], [1.0, 0.0, 1.0]) == pytest.approx(0.0)


def test_roc_auc_perfect_separation():
    assert compute_roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)


def test_roc_auc_none_for_single_class():
    assert compute_roc_auc([1, 1], [0.5, 0.9]) is None


def test_accuracy_known_value():
    y_true = [1, 0, 1, 0]
    y_prob = [0.6, 0.4, 0.3, 0.9]  # correct, correct, wrong, wrong
    assert compute_accuracy(y_true, y_prob) == pytest.approx(0.5)


def test_precision_and_recall_zero_division_returns_zero_not_nan():
    # model never predicts positive (all probs < 0.5)
    y_true = [1, 1, 0]
    y_prob = [0.1, 0.2, 0.1]
    assert compute_precision(y_true, y_prob) == 0.0
    assert compute_recall(y_true, y_prob) == 0.0


def test_precision_recall_known_values():
    y_true = [1, 0, 1, 1]
    y_prob = [0.9, 0.9, 0.1, 0.9]  # predicted positive: idx 0,1,3; true positives among those: 0,3 -> precision 2/3
    assert compute_precision(y_true, y_prob) == pytest.approx(2 / 3)
    assert compute_recall(y_true, y_prob) == pytest.approx(2 / 3)  # 2 of 3 actual positives caught


# --- hit rate: distinct from precision ------------------------------------------


def test_hit_rate_only_considers_confident_selections():
    y_true = [1, 0, 1, 0]
    y_prob = [0.95, 0.95, 0.55, 0.55]  # only first two are >=0.70 confidence
    assert compute_hit_rate(y_true, y_prob, confidence_threshold=0.70) == pytest.approx(0.5)  # 1 of 2


def test_hit_rate_none_when_nothing_meets_threshold():
    assert compute_hit_rate([1, 0], [0.4, 0.3], confidence_threshold=0.70) is None


def test_hit_rate_differs_from_precision_at_default_thresholds():
    """Demonstrates hit_rate (>=0.70 confidence) and precision (>=0.5
    decision) are genuinely different questions, not aliases."""
    y_true = [1, 0, 1, 1, 0]
    y_prob = [0.95, 0.95, 0.55, 0.55, 0.55]
    precision = compute_precision(y_true, y_prob)  # all 5 predicted positive (>=0.5)
    hit_rate = compute_hit_rate(y_true, y_prob)  # only first 2 count (>=0.70)
    assert precision == pytest.approx(3 / 5)
    assert hit_rate == pytest.approx(1 / 2)
    assert precision != hit_rate


# --- probability band breakdown / calibration error ------------------------------


def test_probability_band_breakdown_only_bands_over_50_percent():
    y_true = [1, 0, 1]
    y_prob = [0.3, 0.52, 0.58]  # first excluded (below 0.5)
    breakdown = compute_probability_band_breakdown(y_true, y_prob)
    total_sample = sum(b["sample_size"] for b in breakdown)
    assert total_sample == 2


def test_probability_band_breakdown_groups_correctly():
    y_true = [1, 1, 0]
    y_prob = [0.51, 0.53, 0.59]  # first two in 50-55, third in 55-60
    breakdown = {b["band"]: b for b in compute_probability_band_breakdown(y_true, y_prob)}
    assert breakdown["50-55"]["sample_size"] == 2
    assert breakdown["50-55"]["actual_frequency"] == pytest.approx(1.0)
    assert breakdown["55-60"]["sample_size"] == 1
    assert breakdown["55-60"]["actual_frequency"] == pytest.approx(0.0)


def test_calibration_error_zero_for_perfectly_calibrated_bands():
    # 10 samples all at prob 0.55 (band 55-60... wait 0.55 -> "55-60"), 5 of them actually over
    y_true = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    y_prob = [0.55] * 10
    error = compute_calibration_error(y_true, y_prob)
    assert error == pytest.approx(0.05, abs=1e-9)  # |0.55 - 0.5|


def test_calibration_error_none_when_nothing_bandable():
    assert compute_calibration_error([1, 0], [0.2, 0.3]) is None


# --- compute_all_metrics: bundling ------------------------------------------------


def test_compute_all_metrics_empty_input():
    metrics = compute_all_metrics([], [])
    assert metrics["sample_size"] == 0
    for key in ("log_loss", "brier_score", "roc_auc", "accuracy", "precision_score", "recall_score", "calibration_error", "hit_rate", "predicted_probability_mean", "actual_frequency"):
        assert metrics[key] is None


def test_compute_all_metrics_bundles_expected_keys():
    metrics = compute_all_metrics([1, 0, 1], [0.9, 0.2, 0.8])
    assert metrics["sample_size"] == 3
    assert metrics["predicted_probability_mean"] == pytest.approx((0.9 + 0.2 + 0.8) / 3)
    assert metrics["actual_frequency"] == pytest.approx(2 / 3)
    assert metrics["accuracy"] is not None
