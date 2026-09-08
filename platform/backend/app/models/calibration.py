"""Probability calibration: Platt scaling and Isotonic regression, fit on
validation data, selected by whichever achieves lower validation log
loss — the calibration *method itself* is data-driven per spec ("Select
the calibration approach using validation data"), never a fixed choice.

Both calibrators are serialized to small, self-contained parameter sets
(a sigmoid's (coef, intercept) for Platt; breakpoint arrays for Isotonic)
rather than pickled sklearn objects, so applying a saved calibrator later
never depends on sklearn or on matching library versions - only on numpy
math running against plain JSON.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Union

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from app.backtest.metrics import compute_log_loss

MIN_VALIDATION_ROWS = 10


@dataclass(frozen=True)
class PlattCalibrator:
    coef: float
    intercept: float

    def apply(self, p: float) -> float:
        z = self.coef * p + self.intercept
        return 1.0 / (1.0 + math.exp(-z))

    def to_dict(self) -> dict:
        return {"method": "platt", "coef": self.coef, "intercept": self.intercept}


@dataclass(frozen=True)
class IsotonicCalibrator:
    x_thresholds: list[float]
    y_thresholds: list[float]

    def apply(self, p: float) -> float:
        return float(np.interp(p, self.x_thresholds, self.y_thresholds))

    def to_dict(self) -> dict:
        return {"method": "isotonic", "x_thresholds": self.x_thresholds, "y_thresholds": self.y_thresholds}


Calibrator = Union[PlattCalibrator, IsotonicCalibrator]


def fit_platt(raw_probs: list[float], y_true: list[int]) -> PlattCalibrator:
    X = np.array(raw_probs).reshape(-1, 1)
    model = LogisticRegression()
    model.fit(X, np.array(y_true))
    return PlattCalibrator(coef=float(model.coef_[0][0]), intercept=float(model.intercept_[0]))


def fit_isotonic(raw_probs: list[float], y_true: list[int]) -> IsotonicCalibrator:
    model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    model.fit(raw_probs, y_true)
    return IsotonicCalibrator(x_thresholds=list(model.X_thresholds_), y_thresholds=list(model.y_thresholds_))


def select_calibrator(val_raw_probs: list[float], val_y_true: list[int]) -> tuple[str, Calibrator | None]:
    """Fits both Platt and Isotonic on validation data, returns whichever
    achieves lower validation log loss. Falls back to 'none' (identity)
    if there's too little validation data, or only one class present, to
    fit either reliably."""
    if len(val_raw_probs) < MIN_VALIDATION_ROWS or len(set(val_y_true)) < 2:
        return "none", None

    platt = fit_platt(val_raw_probs, val_y_true)
    isotonic = fit_isotonic(val_raw_probs, val_y_true)

    platt_loss = compute_log_loss(val_y_true, [platt.apply(p) for p in val_raw_probs])
    isotonic_loss = compute_log_loss(val_y_true, [isotonic.apply(p) for p in val_raw_probs])

    if platt_loss is None and isotonic_loss is None:
        return "none", None
    if isotonic_loss is None or (platt_loss is not None and platt_loss <= isotonic_loss):
        return "platt", platt
    return "isotonic", isotonic


def apply_calibration(method: str, calibrator: Calibrator | None, raw_probability: float) -> float:
    if method == "none" or calibrator is None:
        return raw_probability
    return calibrator.apply(raw_probability)


def calibrator_from_dict(data: dict) -> Calibrator:
    if data["method"] == "platt":
        return PlattCalibrator(coef=data["coef"], intercept=data["intercept"])
    if data["method"] == "isotonic":
        return IsotonicCalibrator(x_thresholds=data["x_thresholds"], y_thresholds=data["y_thresholds"])
    raise ValueError(f"unknown calibration method: {data['method']!r}")
