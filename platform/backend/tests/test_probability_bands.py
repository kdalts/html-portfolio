"""Pure unit tests for probability band assignment - no database."""

from app.backtest.probability_bands import assign_band
from app.db.models.evaluation import PROBABILITY_BANDS


def test_below_50_percent_is_unbanded():
    assert assign_band(0.49) is None
    assert assign_band(0.0) is None


def test_lower_boundary_inclusive():
    assert assign_band(0.50) == "50-55"
    assert assign_band(0.55) == "55-60"
    assert assign_band(0.80) == "80+"


def test_upper_boundary_exclusive():
    assert assign_band(0.5499) == "50-55"
    assert assign_band(0.5501) == "55-60"


def test_probability_of_exactly_one_is_in_top_band():
    assert assign_band(1.0) == "80+"


def test_mid_range_bands():
    assert assign_band(0.62) == "60-65"
    assert assign_band(0.71) == "70-75"
    assert assign_band(0.99) == "80+"


def test_every_band_name_is_reachable():
    """Every band in the schema constant has at least one probability
    value that resolves to it - proves the two can't silently drift."""
    reached = set()
    probe = 0.50
    while probe < 1.0:
        band = assign_band(probe)
        if band:
            reached.add(band)
        probe += 0.001
    reached.add(assign_band(0.999))
    assert reached == set(PROBABILITY_BANDS)
