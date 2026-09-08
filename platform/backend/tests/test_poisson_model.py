"""Pure unit tests for the Poisson baseline model - no database."""

import math

import pytest

from app.models.poisson import estimate_poisson, poisson_over_2_5_probability


# --- poisson_over_2_5_probability: verified against hand-computed values -------


def test_zero_lambda_gives_zero_probability():
    assert poisson_over_2_5_probability(0.0) == 0.0


def test_known_reference_value_lambda_2():
    """X ~ Poisson(2): P(X<=2) = e^-2 * (1 + 2 + 2) = 5e^-2 ~= 0.676676.
    P(Over 2.5) = P(X>=3) = 1 - 0.676676 ~= 0.323324 (textbook value)."""
    result = poisson_over_2_5_probability(2.0)
    assert result == pytest.approx(0.323324, abs=1e-5)


def test_known_reference_value_lambda_2_5():
    """lambda=2.5, a common average-ish total-goals rate."""
    lam = 2.5
    expected = 1 - math.exp(-lam) * (1 + lam + lam**2 / 2)
    assert poisson_over_2_5_probability(lam) == pytest.approx(expected)
    assert poisson_over_2_5_probability(lam) == pytest.approx(0.456187, abs=1e-5)


def test_probability_increases_monotonically_with_lambda():
    values = [poisson_over_2_5_probability(lam) for lam in (0.5, 1.0, 2.0, 3.0, 5.0)]
    assert values == sorted(values)


def test_probability_approaches_one_for_large_lambda():
    assert poisson_over_2_5_probability(20.0) > 0.999


def test_probability_bounded_in_zero_one():
    for lam in (0.0, 0.1, 1.0, 2.5, 10.0, 50.0):
        p = poisson_over_2_5_probability(lam)
        assert 0.0 <= p <= 1.0


def test_negative_lambda_raises():
    with pytest.raises(ValueError):
        poisson_over_2_5_probability(-1.0)


# --- estimate_poisson: attack/defense strength formula ---------------------------


def _team_features(*, venue_scored=None, venue_conceded=None, overall_scored=None, overall_conceded=None, window=10):
    return {
        f"venue_last{window}_goals_scored": venue_scored,
        f"venue_last{window}_goals_conceded": venue_conceded,
        f"overall_last{window}_goals_scored": overall_scored,
        f"overall_last{window}_goals_conceded": overall_conceded,
    }


def _match_features(*, league_home_avg, league_away_avg):
    return {"league_home_goals_avg": league_home_avg, "league_away_goals_avg": league_away_avg}


def test_estimate_poisson_matches_hand_calculated_expected_goals():
    """mu_home=1.5, mu_away=1.2. Home team scores 2.0/concedes 1.0 at
    home; away team scores 1.0/concedes 1.8 away.

    expected_home_goals = mu_home * (home_scored/mu_home) * (away_conceded/mu_home)
                         = 1.5 * (2.0/1.5) * (1.8/1.5) = 1.5 * 1.33333 * 1.2 = 2.4
    expected_away_goals = mu_away * (away_scored/mu_away) * (home_conceded/mu_away)
                         = 1.2 * (1.0/1.2) * (1.0/1.2) = 1.2 * 0.83333 * 0.83333 ~= 0.83333
    """
    home = _team_features(venue_scored=2.0, venue_conceded=1.0)
    away = _team_features(venue_scored=1.0, venue_conceded=1.8)
    match = _match_features(league_home_avg=1.5, league_away_avg=1.2)

    result = estimate_poisson(home, away, match)

    assert result.expected_home_goals == pytest.approx(2.4)
    assert result.expected_away_goals == pytest.approx(1.0 * 1.0 / 1.2 * 1.0 / 1.2 * 1.2, rel=1e-9)
    assert result.expected_away_goals == pytest.approx(0.833333, abs=1e-5)
    assert result.lambda_total == pytest.approx(result.expected_home_goals + result.expected_away_goals)
    assert result.probability_over_2_5 == pytest.approx(poisson_over_2_5_probability(result.lambda_total))


def test_estimate_poisson_defense_normalized_against_opposite_league_average():
    """Regression guard for the classic formula mix-up: away_defense must
    be normalized against mu_home (not mu_away), and home_defense against
    mu_away (not mu_home) - because "goals j concedes away" is drawn from
    the same league-wide distribution as "goals home teams score"."""
    home = _team_features(venue_scored=1.0, venue_conceded=1.0)
    away = _team_features(venue_scored=1.0, venue_conceded=1.0)
    # deliberately asymmetric league averages so a mixed-up formula would
    # produce a different, detectably wrong number
    match = _match_features(league_home_avg=2.0, league_away_avg=0.5)

    result = estimate_poisson(home, away, match)

    # expected_home_goals = 2.0 * (1.0/2.0) * (1.0/2.0) = 0.5
    assert result.expected_home_goals == pytest.approx(0.5)
    # expected_away_goals = 0.5 * (1.0/0.5) * (1.0/0.5) = 2.0
    assert result.expected_away_goals == pytest.approx(2.0)


def test_estimate_poisson_falls_back_to_overall_when_venue_missing():
    home = _team_features(venue_scored=None, venue_conceded=None, overall_scored=1.8, overall_conceded=1.1)
    away = _team_features(venue_scored=1.0, venue_conceded=1.0)
    match = _match_features(league_home_avg=1.5, league_away_avg=1.2)

    result = estimate_poisson(home, away, match)
    assert result is not None  # fallback allowed the computation to proceed


def test_estimate_poisson_none_when_league_average_missing():
    home = _team_features(venue_scored=1.5, venue_conceded=1.0)
    away = _team_features(venue_scored=1.0, venue_conceded=1.0)
    match = _match_features(league_home_avg=None, league_away_avg=1.2)
    assert estimate_poisson(home, away, match) is None


def test_estimate_poisson_none_when_league_average_is_zero():
    home = _team_features(venue_scored=1.5, venue_conceded=1.0)
    away = _team_features(venue_scored=1.0, venue_conceded=1.0)
    match = _match_features(league_home_avg=0.0, league_away_avg=1.2)
    assert estimate_poisson(home, away, match) is None


def test_estimate_poisson_none_when_team_has_no_history_at_all():
    home = _team_features()  # every stat None
    away = _team_features(venue_scored=1.0, venue_conceded=1.0)
    match = _match_features(league_home_avg=1.5, league_away_avg=1.2)
    assert estimate_poisson(home, away, match) is None


def test_estimate_poisson_respects_window_parameter():
    home = _team_features(venue_scored=2.0, venue_conceded=1.0, window=5)
    away = _team_features(venue_scored=1.0, venue_conceded=1.0, window=5)
    match = _match_features(league_home_avg=1.5, league_away_avg=1.2)

    # no last10 columns present at all -> None with the default window
    assert estimate_poisson(home, away, match, window=10) is None
    # but window=5 finds the data
    assert estimate_poisson(home, away, match, window=5) is not None


def test_estimate_poisson_expected_goals_never_negative():
    home = _team_features(venue_scored=0.0, venue_conceded=0.0)
    away = _team_features(venue_scored=0.0, venue_conceded=0.0)
    match = _match_features(league_home_avg=1.5, league_away_avg=1.2)

    result = estimate_poisson(home, away, match)
    assert result.expected_home_goals >= 0.0
    assert result.expected_away_goals >= 0.0
    assert result.probability_over_2_5 == 0.0
