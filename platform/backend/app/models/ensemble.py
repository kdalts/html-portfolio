"""Ensemble weighting for raw_ensemble_probability.

Per spec: weights are fit on validation data, never fixed/assumed
permanently, and combine whichever of poisson_probability/ml_probability/
sportmonks_probability are actually available. A source is only fitted a
non-zero weight if it has sufficient coverage (non-null rate) in the
validation set — sportmonks_probability, entirely absent until Phase 9
populates it, simply gets weight 0.0 here rather than a guessed value;
re-fitting later (once real Sportmonks data exists) is how it earns a
real weight.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

DEFAULT_SOURCES = ("poisson_probability", "ml_probability", "sportmonks_probability")
DEFAULT_MIN_COVERAGE = 0.8


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max()
    exp = np.exp(z)
    return exp / exp.sum()


def fit_ensemble_weights(
    validation_rows: list[dict],
    *,
    sources: tuple[str, ...] = DEFAULT_SOURCES,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> dict[str, float]:
    """Fits non-negative weights (summing to 1) over whichever `sources`
    have at least `min_coverage` non-null values in validation_rows,
    minimizing validation log loss. Sources below the coverage threshold
    get a fixed weight of 0.0 - never fitted, never guessed."""
    n = len(validation_rows)
    weights = {s: 0.0 for s in sources}
    if n == 0:
        return weights

    available = [
        s for s in sources if sum(1 for row in validation_rows if row.get(s) is not None) / n >= min_coverage
    ]
    if not available:
        return weights

    complete_rows = [
        row
        for row in validation_rows
        if all(row.get(s) is not None for s in available) and row.get("over_2_5") is not None
    ]
    if len(complete_rows) < 2:
        equal = 1.0 / len(available)
        for s in available:
            weights[s] = equal
        return weights

    y = np.array([row["over_2_5"] for row in complete_rows], dtype=float)
    X = np.array([[row[s] for s in available] for row in complete_rows], dtype=float)

    def loss(z: np.ndarray) -> float:
        w = _softmax(np.asarray(z))
        p = np.clip(X @ w, 1e-9, 1 - 1e-9)
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    result = minimize(loss, np.zeros(len(available)), method="Nelder-Mead")
    fitted = _softmax(result.x)
    for s, w in zip(available, fitted):
        weights[s] = float(w)
    return weights


def compute_raw_ensemble_probability(row: dict, weights: dict[str, float]) -> float | None:
    """Weighted combination using whichever sources are both weighted
    (> 0) and present on this specific row - renormalized over just
    those, so one row missing a source falls back to the other weighted
    sources rather than silently producing a too-small number."""
    usable = [(s, w) for s, w in weights.items() if w > 0 and row.get(s) is not None]
    if not usable:
        return None
    total_weight = sum(w for _, w in usable)
    return sum(row[s] * w for s, w in usable) / total_weight
