"""Pure unit tests for probability calibration - no database."""

import random

from app.backtest.metrics import compute_log_loss
from app.models.calibration import (
    apply_calibration,
    calibrator_from_dict,
    fit_isotonic,
    fit_platt,
    select_calibrator,
)


def _overconfident_dataset(n=200, seed=0):
    """Raw probabilities systematically too extreme relative to the true
    rate - calibration should pull them back toward the actual frequency,
    and log loss should improve after calibration."""
    rng = random.Random(seed)
    raw_probs, y_true = [], []
    for _ in range(n):
        true_rate = rng.uniform(0.3, 0.7)
        label = 1 if rng.random() < true_rate else 0
        # push the "model's" stated probability further from 0.5 than it should be
        overconfident = 0.5 + (true_rate - 0.5) * 2.5
        raw_probs.append(min(max(overconfident, 0.01), 0.99))
        y_true.append(label)
    return raw_probs, y_true


def test_select_calibrator_falls_back_to_none_with_too_little_data():
    method, calibrator = select_calibrator([0.6, 0.7, 0.8], [1, 0, 1])
    assert method == "none"
    assert calibrator is None


def test_select_calibrator_falls_back_to_none_with_single_class():
    raw = [0.6] * 20
    y = [1] * 20
    method, calibrator = select_calibrator(raw, y)
    assert method == "none"


def test_calibration_improves_log_loss_on_overconfident_predictions():
    raw_probs, y_true = _overconfident_dataset()
    method, calibrator = select_calibrator(raw_probs, y_true)
    assert method in ("platt", "isotonic")

    calibrated = [apply_calibration(method, calibrator, p) for p in raw_probs]
    raw_loss = compute_log_loss(y_true, raw_probs)
    calibrated_loss = compute_log_loss(y_true, calibrated)
    assert calibrated_loss < raw_loss


def test_apply_calibration_none_is_identity():
    assert apply_calibration("none", None, 0.73) == 0.73


def test_platt_calibrator_round_trips_through_dict():
    raw_probs, y_true = _overconfident_dataset(seed=1)
    calibrator = fit_platt(raw_probs, y_true)
    original = calibrator.apply(0.65)

    restored = calibrator_from_dict(calibrator.to_dict())
    assert restored.apply(0.65) == original


def test_isotonic_calibrator_round_trips_through_dict():
    raw_probs, y_true = _overconfident_dataset(seed=2)
    calibrator = fit_isotonic(raw_probs, y_true)
    original = calibrator.apply(0.65)

    restored = calibrator_from_dict(calibrator.to_dict())
    assert restored.apply(0.65) == original


def test_isotonic_calibrator_is_monotonic():
    raw_probs, y_true = _overconfident_dataset(seed=3)
    calibrator = fit_isotonic(raw_probs, y_true)
    outputs = [calibrator.apply(p / 100) for p in range(0, 101, 5)]
    assert outputs == sorted(outputs)


def test_calibrated_outputs_stay_within_zero_one():
    raw_probs, y_true = _overconfident_dataset(seed=4)
    method, calibrator = select_calibrator(raw_probs, y_true)
    for p in [0.0, 0.01, 0.5, 0.99, 1.0]:
        result = apply_calibration(method, calibrator, p)
        assert 0.0 <= result <= 1.0
