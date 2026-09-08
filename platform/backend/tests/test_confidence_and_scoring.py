"""Pure unit tests for confidence_score and ranking_score - no database."""

import pytest

from app.ranking.confidence import SINGLE_SOURCE_AGREEMENT_DEFAULT, compute_agreement_factor, compute_confidence_score
from app.ranking.scoring import EDGE_BOOST_WEIGHT, compute_ranking_score


# --- agreement / confidence --------------------------------------------------------


def test_agreement_is_high_when_sources_agree():
    assert compute_agreement_factor([0.65, 0.66, 0.64]) > 0.9


def test_agreement_is_low_when_sources_diverge_widely():
    assert compute_agreement_factor([0.2, 0.9]) < 0.5


def test_single_source_uses_documented_default():
    assert compute_agreement_factor([0.7]) == SINGLE_SOURCE_AGREEMENT_DEFAULT
    assert compute_agreement_factor([]) == SINGLE_SOURCE_AGREEMENT_DEFAULT


def test_confidence_score_is_product_of_three_factors():
    score = compute_confidence_score(
        data_completeness_score=0.8, league_reliability_score=0.5, available_probabilities=[0.6, 0.6]
    )
    # agreement should be ~1.0 for identical sources
    assert score == pytest.approx(0.8 * 0.5 * 1.0, abs=0.02)


def test_confidence_score_zero_when_completeness_missing():
    score = compute_confidence_score(
        data_completeness_score=None, league_reliability_score=0.9, available_probabilities=[0.6, 0.6]
    )
    assert score == 0.0


def test_confidence_score_zero_when_league_reliability_missing():
    score = compute_confidence_score(
        data_completeness_score=0.9, league_reliability_score=None, available_probabilities=[0.6, 0.6]
    )
    assert score == 0.0


def test_confidence_score_bounded_zero_one():
    score = compute_confidence_score(
        data_completeness_score=1.0, league_reliability_score=1.0, available_probabilities=[0.5, 0.5, 0.5]
    )
    assert 0.0 <= score <= 1.0


def test_confidence_is_distinct_from_probability_and_edge():
    """Two fixtures with the IDENTICAL final_probability can have very
    different confidence - proving confidence isn't just a reflection of
    probability (or of edge, which isn't an input here at all)."""
    high_confidence = compute_confidence_score(
        data_completeness_score=0.9, league_reliability_score=0.9, available_probabilities=[0.7, 0.71, 0.69]
    )
    low_confidence = compute_confidence_score(
        data_completeness_score=0.2, league_reliability_score=0.3, available_probabilities=[0.7]
    )
    assert high_confidence > low_confidence


# --- ranking score -----------------------------------------------------------------


def test_ranking_score_base_case_no_edge():
    score = compute_ranking_score(final_probability=0.7, confidence_score=0.5, edge=None)
    assert score == pytest.approx(0.35)


def test_positive_edge_boosts_score():
    without_edge = compute_ranking_score(final_probability=0.7, confidence_score=0.5, edge=None)
    with_edge = compute_ranking_score(final_probability=0.7, confidence_score=0.5, edge=0.1)
    assert with_edge > without_edge
    assert with_edge == pytest.approx(0.7 * 0.5 + EDGE_BOOST_WEIGHT * 0.1 * 0.5)


def test_negative_edge_never_penalizes():
    without_edge = compute_ranking_score(final_probability=0.7, confidence_score=0.5, edge=None)
    with_negative_edge = compute_ranking_score(final_probability=0.7, confidence_score=0.5, edge=-0.2)
    assert with_negative_edge == pytest.approx(without_edge)


def test_edge_boost_is_gated_by_confidence():
    """The same positive edge contributes less to ranking_score at lower
    confidence - a big edge from an unreliable prediction shouldn't be
    treated the same as one from a trusted prediction."""
    low_confidence_boost = compute_ranking_score(final_probability=0.7, confidence_score=0.1, edge=0.2)
    high_confidence_boost = compute_ranking_score(final_probability=0.7, confidence_score=0.9, edge=0.2)
    low_edge_contribution = low_confidence_boost - 0.7 * 0.1
    high_edge_contribution = high_confidence_boost - 0.7 * 0.9
    assert low_edge_contribution < high_edge_contribution
