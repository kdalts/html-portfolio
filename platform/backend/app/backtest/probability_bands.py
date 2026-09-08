"""Assigns a predicted probability to one of the platform's fixed
probability bands (50-55, 55-60, ..., 80+), reusing the PROBABILITY_BANDS
tuple from the schema (app.db.models.evaluation) so the two definitions
can never drift apart.

Returns None for any probability below 0.5 - this platform only bands
"Over" selections; a prediction leaning Under isn't part of the
calibration question the bands exist to answer.
"""

from __future__ import annotations

from app.db.models.evaluation import PROBABILITY_BANDS


def _band_bounds(band: str) -> tuple[float, float]:
    if band == "80+":
        return 0.80, 1.0000001  # inclusive of probability == 1.0
    low_str, high_str = band.split("-")
    return int(low_str) / 100, int(high_str) / 100


_BAND_BOUNDS: dict[str, tuple[float, float]] = {band: _band_bounds(band) for band in PROBABILITY_BANDS}


def assign_band(probability: float) -> str | None:
    if probability < 0.5:
        return None
    for band, (low, high) in _BAND_BOUNDS.items():
        if low <= probability < high:
            return band
    return None
