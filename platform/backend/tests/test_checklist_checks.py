"""Pure tests for the 13 scored checklist check functions - no database,
each check exercised against hand-reasoned inputs: a clear pass, a clear
fail, and the missing-data case returning None (N/A), never a guessed
True/False."""

from app.checklist.checks import (
    check_attack_defence_split,
    check_btts_rate,
    check_clean_sheet_rate,
    check_combined_goals,
    check_combined_xg,
    check_early_goals,
    check_h2h_last3,
    check_late_goals,
    check_league_gap,
    check_recent_form,
    check_sample_size,
    check_shots_on_target,
    check_vs_league_average,
)


def test_sample_size_never_returns_none():
    assert check_sample_size(5, 5) is True
    assert check_sample_size(4, 10) is False
    assert check_sample_size(10, 4) is False


def test_btts_rate_pass_fail_and_missing():
    assert check_btts_rate(0.65, 0.70) is True
    assert check_btts_rate(0.65, 0.50) is False
    assert check_btts_rate(None, 0.70) is None


def test_clean_sheet_rate_uses_below_threshold():
    assert check_clean_sheet_rate(0.20, 0.30) is True
    assert check_clean_sheet_rate(0.20, 0.40) is False
    assert check_clean_sheet_rate(None, None) is None


def test_combined_goals_sums_both_teams():
    assert check_combined_goals(2.0, 1.6) is True  # 3.6 > 3.5
    assert check_combined_goals(1.5, 1.5) is False  # 3.0, not over 3.5
    assert check_combined_goals(2.0, None) is None


def test_league_gap_requires_home_higher_and_min_gap():
    assert check_league_gap(home_position=2, away_position=10) is True  # gap 8, home higher
    assert check_league_gap(home_position=10, away_position=2) is False  # home is lower-placed
    assert check_league_gap(home_position=2, away_position=5) is False  # gap only 3, below min_gap=5
    assert check_league_gap(None, 5) is None


def test_shots_on_target_requires_both_over_threshold():
    assert check_shots_on_target(5.0, 4.5) is True
    assert check_shots_on_target(5.0, 3.0) is False
    assert check_shots_on_target(None, 4.5) is None


def test_attack_defence_split_is_home_for_vs_away_against():
    assert check_attack_defence_split(home_goals_for_avg=3.5, away_goals_against_avg=3.2) is True
    assert check_attack_defence_split(home_goals_for_avg=2.0, away_goals_against_avg=3.2) is False
    assert check_attack_defence_split(None, 3.2) is None


def test_combined_xg_sums_all_four_values():
    assert check_combined_xg(1.5, 1.0, 1.0, 0.5) is True  # sums to 4.0 > 2.5
    assert check_combined_xg(0.4, 0.4, 0.4, 0.4) is False  # sums to 1.6
    assert check_combined_xg(None, 1.0, 1.0, 0.5) is None


def test_h2h_last3_requires_exactly_three_and_all_over_25():
    assert check_h2h_last3([3, 4, 5]) is True
    assert check_h2h_last3([3, 2, 5]) is False  # one match was exactly 2 goals, not over 2.5
    assert check_h2h_last3([3, 4]) is None  # fewer than 3 meetings on record
    assert check_h2h_last3(None) is None


def test_recent_form_uses_over25_rate_threshold():
    assert check_recent_form(0.60, 0.80) is True
    assert check_recent_form(0.60, 0.40) is False
    assert check_recent_form(None, 0.80) is None


def test_vs_league_average_compares_venue_specific_averages():
    assert check_vs_league_average(2.0, 1.5, 1.6, 1.2) is True
    assert check_vs_league_average(1.0, 1.5, 1.6, 1.2) is False  # home team below its venue's league average
    assert check_vs_league_average(2.0, 1.5, None, 1.2) is None


def test_early_and_late_goals_are_none_with_no_inputs():
    # always N/A today - no goal-timing data is ingested anywhere in this
    # platform yet; verified here so a future data source just needs to
    # pass real percentages in, not touch this function.
    assert check_early_goals(None, None) is None
    assert check_late_goals(None, None) is None
    assert check_early_goals(0.5, 0.5) is True
    assert check_late_goals(0.1, 0.5) is False
