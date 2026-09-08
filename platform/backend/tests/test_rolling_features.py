"""Pure unit tests for app.features.rolling — no database. These are the
most important leakage tests in the codebase: they prove the rolling
window strictly respects the "before" cutoff."""

from datetime import datetime, timezone

import pytest

from app.db.models.features import FEATURE_CONTEXTS, ROLLING_WINDOWS, STAT_KEYS, _team_feature_column_names
from app.features.rolling import _STAT_ACCESSORS, compute_rolling_stats, compute_team_rolling_features
from app.features.team_match_log import TeamAppearance

UTC = timezone.utc


def _appearance(
    kickoff,
    *,
    is_home=True,
    goals_for=1,
    goals_against=1,
    xg_for=1.0,
    xg_against=1.0,
    shots_for=10.0,
    shots_on_target_for=4.0,
    big_chances_for=2.0,
    corners_for=5.0,
    fixture_id=None,
    opponent_id=99,
) -> TeamAppearance:
    return TeamAppearance(
        fixture_id=fixture_id or kickoff.toordinal(),
        opponent_id=opponent_id,
        kickoff=kickoff,
        is_home=is_home,
        league_id=1,
        season_id=1,
        goals_for=goals_for,
        goals_against=goals_against,
        xg_for=xg_for,
        xg_against=xg_against,
        shots_for=shots_for,
        shots_on_target_for=shots_on_target_for,
        big_chances_for=big_chances_for,
        corners_for=corners_for,
    )


def test_stat_accessors_cover_every_stat_key():
    assert set(_STAT_ACCESSORS) == set(STAT_KEYS)


# --- leakage boundary: the core guarantee of this module -----------------------


def test_appearance_exactly_at_cutoff_is_excluded():
    cutoff = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)
    appearances = [_appearance(cutoff, goals_for=5, goals_against=5)]
    stats = compute_rolling_stats(appearances, before=cutoff, window=3)
    assert stats["matches_played"] == 0
    assert stats["goals_scored"] is None


def test_appearance_strictly_before_cutoff_is_included():
    cutoff = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)
    earlier = datetime(2024, 8, 10, 15, 0, tzinfo=UTC)
    appearances = [_appearance(earlier, goals_for=3, goals_against=0)]
    stats = compute_rolling_stats(appearances, before=cutoff, window=3)
    assert stats["matches_played"] == 1
    assert stats["goals_scored"] == 3


def test_future_appearances_relative_to_cutoff_are_excluded():
    """A team's history can include matches AFTER the target fixture
    (e.g. computing historical features for backtesting, where later
    matches already exist in the DB) - these must never leak in."""
    cutoff = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)
    later = datetime(2024, 9, 1, tzinfo=UTC)
    appearances = [_appearance(later, goals_for=9, goals_against=9)]
    stats = compute_rolling_stats(appearances, before=cutoff, window=3)
    assert stats["matches_played"] == 0


# --- window / averaging correctness ---------------------------------------------


def test_averages_over_exact_window_size():
    cutoff = datetime(2024, 8, 20, tzinfo=UTC)
    appearances = [
        _appearance(datetime(2024, 8, 1, tzinfo=UTC), goals_for=1, goals_against=0),
        _appearance(datetime(2024, 8, 5, tzinfo=UTC), goals_for=2, goals_against=1),
        _appearance(datetime(2024, 8, 10, tzinfo=UTC), goals_for=3, goals_against=2),
    ]
    stats = compute_rolling_stats(appearances, before=cutoff, window=3)
    assert stats["matches_played"] == 3
    assert stats["goals_scored"] == pytest.approx(2.0)  # (1+2+3)/3
    assert stats["goals_conceded"] == pytest.approx(1.0)  # (0+1+2)/3


def test_window_takes_only_the_most_recent_n():
    cutoff = datetime(2024, 9, 1, tzinfo=UTC)
    appearances = [
        _appearance(datetime(2024, 1, 1, tzinfo=UTC), goals_for=100, goals_against=0),  # too old, excluded
        _appearance(datetime(2024, 8, 1, tzinfo=UTC), goals_for=1, goals_against=0),
        _appearance(datetime(2024, 8, 5, tzinfo=UTC), goals_for=2, goals_against=0),
        _appearance(datetime(2024, 8, 10, tzinfo=UTC), goals_for=3, goals_against=0),
    ]
    stats = compute_rolling_stats(appearances, before=cutoff, window=3)
    assert stats["matches_played"] == 3
    assert stats["goals_scored"] == pytest.approx(2.0)  # (1+2+3)/3, the 100 dropped


def test_fewer_than_window_matches_available():
    cutoff = datetime(2024, 8, 20, tzinfo=UTC)
    appearances = [_appearance(datetime(2024, 8, 1, tzinfo=UTC), goals_for=4, goals_against=0)]
    stats = compute_rolling_stats(appearances, before=cutoff, window=10)
    assert stats["matches_played"] == 1
    assert stats["goals_scored"] == 4.0


def test_zero_prior_matches_yields_all_none():
    cutoff = datetime(2024, 8, 20, tzinfo=UTC)
    stats = compute_rolling_stats([], before=cutoff, window=5)
    assert stats["matches_played"] == 0
    for stat_name in STAT_KEYS:
        assert stats[stat_name] is None


def test_stat_with_all_missing_values_is_none_not_zero():
    cutoff = datetime(2024, 8, 20, tzinfo=UTC)
    appearances = [
        _appearance(datetime(2024, 8, 1, tzinfo=UTC), xg_for=None),
        _appearance(datetime(2024, 8, 5, tzinfo=UTC), xg_for=None),
    ]
    stats = compute_rolling_stats(appearances, before=cutoff, window=5)
    assert stats["matches_played"] == 2
    assert stats["xg"] is None  # not 0.0 - genuinely unknown, not "no expected goals"


def test_stat_partial_missing_values_averages_only_present_ones():
    cutoff = datetime(2024, 8, 20, tzinfo=UTC)
    appearances = [
        _appearance(datetime(2024, 8, 1, tzinfo=UTC), xg_for=2.0),
        _appearance(datetime(2024, 8, 5, tzinfo=UTC), xg_for=None),
    ]
    stats = compute_rolling_stats(appearances, before=cutoff, window=5)
    assert stats["xg"] == 2.0  # averaged over the one present value, not (2.0+0)/2


# --- btts / over_2_5 percentage correctness --------------------------------------


def test_btts_and_over_2_5_percentages():
    cutoff = datetime(2024, 8, 20, tzinfo=UTC)
    appearances = [
        _appearance(datetime(2024, 8, 1, tzinfo=UTC), goals_for=2, goals_against=1),  # btts, over
        _appearance(datetime(2024, 8, 5, tzinfo=UTC), goals_for=1, goals_against=0),  # not btts, not over
        _appearance(datetime(2024, 8, 10, tzinfo=UTC), goals_for=0, goals_against=3),  # btts=false, over=true
        _appearance(datetime(2024, 8, 12, tzinfo=UTC), goals_for=2, goals_against=2),  # btts, over
    ]
    stats = compute_rolling_stats(appearances, before=cutoff, window=4)
    assert stats["btts_pct"] == pytest.approx(2 / 4)
    assert stats["over_2_5_pct"] == pytest.approx(3 / 4)


# --- team_rolling_features: overall vs venue context, and column alignment ------


def test_venue_context_only_uses_matching_venue_appearances():
    cutoff = datetime(2024, 9, 1, tzinfo=UTC)
    appearances = [
        _appearance(datetime(2024, 8, 1, tzinfo=UTC), is_home=True, goals_for=5, goals_against=0),
        _appearance(datetime(2024, 8, 5, tzinfo=UTC), is_home=False, goals_for=1, goals_against=1),
    ]
    home_features = compute_team_rolling_features(appearances, before=cutoff, target_is_home=True)
    assert home_features["overall_last10_matches_played"] == 2  # overall sees both
    assert home_features["venue_last10_matches_played"] == 1  # venue sees only the home appearance
    assert home_features["venue_last10_goals_scored"] == 5.0

    away_features = compute_team_rolling_features(appearances, before=cutoff, target_is_home=False)
    assert away_features["venue_last10_matches_played"] == 1
    assert away_features["venue_last10_goals_scored"] == 1.0


def test_team_rolling_features_column_set_matches_team_features_schema():
    cutoff = datetime(2024, 9, 1, tzinfo=UTC)
    appearances = [_appearance(datetime(2024, 8, 1, tzinfo=UTC))]
    result = compute_team_rolling_features(appearances, before=cutoff, target_is_home=True)
    assert set(result.keys()) == set(_team_feature_column_names())


def test_team_rolling_features_produces_every_window_and_context():
    cutoff = datetime(2024, 9, 1, tzinfo=UTC)
    result = compute_team_rolling_features([], before=cutoff, target_is_home=True)
    for context in FEATURE_CONTEXTS:
        for window in ROLLING_WINDOWS:
            assert f"{context}_last{window}_matches_played" in result
