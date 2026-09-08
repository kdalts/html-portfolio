"""Pure unit tests for ensemble weight fitting - no database."""

import random

import pytest

from app.models.ensemble import compute_raw_ensemble_probability, fit_ensemble_weights


def _rows(n, *, seed=0, informative_source="poisson_probability", noise_source="ml_probability"):
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        signal = rng.uniform(0, 1)
        label = 1 if signal > 0.5 else 0
        rows.append(
            {
                informative_source: signal,
                noise_source: rng.uniform(0, 1),  # uninformative
                "sportmonks_probability": None,  # not yet populated (pre-Phase-9)
                "over_2_5": label,
            }
        )
    return rows


def test_weights_sum_to_one_over_available_sources():
    rows = _rows(200)
    weights = fit_ensemble_weights(rows)
    assert weights["sportmonks_probability"] == 0.0  # entirely missing -> never fitted
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)


def test_unavailable_source_gets_zero_weight_never_guessed():
    rows = _rows(200)
    weights = fit_ensemble_weights(rows)
    assert weights["sportmonks_probability"] == 0.0


def test_informative_source_gets_more_weight_than_noise():
    rows = _rows(300, seed=1)
    weights = fit_ensemble_weights(rows)
    assert weights["poisson_probability"] > weights["ml_probability"]


def test_empty_validation_set_returns_all_zero_weights():
    weights = fit_ensemble_weights([])
    assert all(w == 0.0 for w in weights.values())


def test_below_coverage_threshold_source_excluded():
    rows = _rows(100)
    # sportmonks_probability present on only 10% of rows -> below default 80% coverage
    for i, row in enumerate(rows):
        if i % 10 == 0:
            row["sportmonks_probability"] = 0.5
    weights = fit_ensemble_weights(rows)
    assert weights["sportmonks_probability"] == 0.0


def test_above_coverage_threshold_source_included():
    rows = _rows(100, seed=2)
    for row in rows:
        row["sportmonks_probability"] = row["poisson_probability"]  # fully covered, correlated w/ label
    weights = fit_ensemble_weights(rows)
    assert weights["sportmonks_probability"] > 0.0


# --- compute_raw_ensemble_probability ---------------------------------------------


def test_raw_ensemble_probability_weighted_average():
    weights = {"poisson_probability": 0.6, "ml_probability": 0.4, "sportmonks_probability": 0.0}
    row = {"poisson_probability": 0.8, "ml_probability": 0.2, "sportmonks_probability": None}
    result = compute_raw_ensemble_probability(row, weights)
    assert result == pytest.approx(0.8 * 0.6 + 0.2 * 0.4)


def test_raw_ensemble_probability_renormalizes_when_a_source_missing_on_this_row():
    weights = {"poisson_probability": 0.5, "ml_probability": 0.5, "sportmonks_probability": 0.0}
    row = {"poisson_probability": 0.9, "ml_probability": None, "sportmonks_probability": None}
    # only poisson available on this row -> falls back to it entirely, not halved
    assert compute_raw_ensemble_probability(row, weights) == pytest.approx(0.9)


def test_raw_ensemble_probability_none_when_nothing_usable():
    weights = {"poisson_probability": 1.0, "ml_probability": 0.0, "sportmonks_probability": 0.0}
    row = {"poisson_probability": None, "ml_probability": 0.5, "sportmonks_probability": 0.5}
    assert compute_raw_ensemble_probability(row, weights) is None
