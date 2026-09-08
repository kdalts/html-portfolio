"""Pure unit tests for league_reliability_score - no database."""

import pytest

from app.ranking.league_reliability import (
    ELIGIBILITY_MIN_SAMPLE_SIZE,
    ELIGIBILITY_SCORE_THRESHOLD,
    MAX_ACCEPTABLE_BRIER,
    MAX_ACCEPTABLE_CALIBRATION_ERROR,
    MIN_RELIABLE_SAMPLE_SIZE,
    compute_reliability_score,
)


def test_zero_sample_size_is_zero_score():
    assert compute_reliability_score(sample_size=0, brier_score=0.1, calibration_error=0.02) == 0.0


def test_perfect_metrics_at_full_sample_size_scores_near_one():
    score = compute_reliability_score(sample_size=MIN_RELIABLE_SAMPLE_SIZE, brier_score=0.0, calibration_error=0.0)
    assert score == pytest.approx(1.0)


def test_low_sample_size_scales_down_proportionally():
    score = compute_reliability_score(
        sample_size=MIN_RELIABLE_SAMPLE_SIZE // 2, brier_score=0.0, calibration_error=0.0
    )
    assert score == pytest.approx(0.5)


def test_poor_brier_score_penalizes_even_with_full_sample():
    good = compute_reliability_score(sample_size=MIN_RELIABLE_SAMPLE_SIZE, brier_score=0.0, calibration_error=0.0)
    poor = compute_reliability_score(
        sample_size=MIN_RELIABLE_SAMPLE_SIZE, brier_score=MAX_ACCEPTABLE_BRIER, calibration_error=0.0
    )
    assert poor < good
    assert poor == pytest.approx(0.0, abs=1e-9)


def test_poor_calibration_penalizes_even_with_full_sample():
    poor = compute_reliability_score(
        sample_size=MIN_RELIABLE_SAMPLE_SIZE, brier_score=0.0, calibration_error=MAX_ACCEPTABLE_CALIBRATION_ERROR
    )
    assert poor == pytest.approx(0.0, abs=1e-9)


def test_score_never_goes_negative_for_extreme_inputs():
    score = compute_reliability_score(sample_size=1_000_000, brier_score=1.0, calibration_error=1.0)
    assert score >= 0.0


def test_missing_metrics_do_not_crash_and_use_sample_size_alone():
    score = compute_reliability_score(sample_size=MIN_RELIABLE_SAMPLE_SIZE, brier_score=None, calibration_error=None)
    assert score == pytest.approx(1.0)  # unmeasured dimensions aren't penalized beyond sample size


def test_multiplicative_combination_is_stricter_than_averaging():
    """Good sample size, but both quality dimensions mediocre -> score
    should be noticeably worse than either dimension alone, proving the
    combination is multiplicative rather than an average that would hide
    a weak dimension behind stronger ones."""
    half_brier_penalty = compute_reliability_score(
        sample_size=MIN_RELIABLE_SAMPLE_SIZE, brier_score=MAX_ACCEPTABLE_BRIER / 2, calibration_error=0.0
    )
    half_calibration_penalty = compute_reliability_score(
        sample_size=MIN_RELIABLE_SAMPLE_SIZE, brier_score=0.0, calibration_error=MAX_ACCEPTABLE_CALIBRATION_ERROR / 2
    )
    both_half_penalties = compute_reliability_score(
        sample_size=MIN_RELIABLE_SAMPLE_SIZE,
        brier_score=MAX_ACCEPTABLE_BRIER / 2,
        calibration_error=MAX_ACCEPTABLE_CALIBRATION_ERROR / 2,
    )
    assert both_half_penalties < min(half_brier_penalty, half_calibration_penalty)


def test_eligibility_constants_are_internally_consistent():
    assert 0.0 < ELIGIBILITY_SCORE_THRESHOLD < 1.0
    assert ELIGIBILITY_MIN_SAMPLE_SIZE < MIN_RELIABLE_SAMPLE_SIZE
