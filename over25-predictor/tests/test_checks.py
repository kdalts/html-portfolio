"""
Sanity tests for the 15-point checklist logic, using fabricated stats (no
network / API key required). Run with:

    python -m pytest tests/test_checks.py -v

or, without pytest installed:

    python tests/test_checks.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks import (
    MatchContext,
    check_1_sample_size,
    check_2_btts_rate,
    check_4_combined_goals_per_game,
    check_5_league_gap,
    check_7_attack_vs_defence_split,
    check_8_expected_goals,
    check_9_h2h_over25,
    check_10_recent_form_over25,
    check_11_vs_league_average,
    context_notes,
    key_players_missing,
)
from team_stats import RecentMatch, TeamSeasonStats


def make_team(**overrides) -> TeamSeasonStats:
    defaults = dict(
        team_id=1, team_name="Test FC", league_id=1, season=2025,
        games_played=10, goals_for_avg=1.8, goals_against_avg=1.2,
        clean_sheet_rate=0.2, btts_rate=0.7, shots_on_target_avg=5.0,
        recent_matches=[], xg_for_avg=1.6, xga_avg=1.1,
        early_goal_rate=0.5, early_goal_sample_size=8,
        late_goal_rate=0.5, late_goal_sample_size=8,
        table_position=3, league_size=20, is_relegation_zone=False,
        injuries=[],
    )
    defaults.update(overrides)
    return TeamSeasonStats(**defaults)


def make_ctx(home=None, away=None, **overrides) -> MatchContext:
    defaults = dict(
        home=home or make_team(team_name="Home FC"),
        away=away or make_team(team_id=2, team_name="Away FC"),
        min_games_played=5,
        recent_form_games=5,
        h2h_totals=[3, 4, 3],
        home_league_avg_goals=2.6,
        away_league_avg_goals=2.6,
        competition_type="League",
    )
    defaults.update(overrides)
    return MatchContext(**defaults)


def test_check_1_sample_size():
    ctx = make_ctx(home=make_team(games_played=4))
    assert check_1_sample_size(ctx).passed is False
    ctx = make_ctx(home=make_team(games_played=6), away=make_team(team_id=2, games_played=6))
    assert check_1_sample_size(ctx).passed is True


def test_check_2_btts_rate():
    ctx = make_ctx(home=make_team(btts_rate=0.65), away=make_team(team_id=2, btts_rate=0.61))
    assert check_2_btts_rate(ctx).passed is True
    ctx = make_ctx(home=make_team(btts_rate=0.5))
    assert check_2_btts_rate(ctx).passed is False
    ctx = make_ctx(home=make_team(btts_rate=None))
    assert check_2_btts_rate(ctx).passed is None


def test_check_4_combined_goals():
    ctx = make_ctx(home=make_team(goals_for_avg=2.0), away=make_team(team_id=2, goals_for_avg=1.6))
    assert check_4_combined_goals_per_game(ctx).passed is True  # 3.6 > 3.5
    ctx = make_ctx(home=make_team(goals_for_avg=1.0), away=make_team(team_id=2, goals_for_avg=1.0))
    assert check_4_combined_goals_per_game(ctx).passed is False


def test_check_5_league_gap():
    ctx = make_ctx(home=make_team(table_position=2), away=make_team(team_id=2, table_position=10))
    assert check_5_league_gap(ctx).passed is True
    ctx = make_ctx(home=make_team(table_position=8), away=make_team(team_id=2, table_position=10))
    assert check_5_league_gap(ctx).passed is False  # gap only 2
    ctx = make_ctx(home=make_team(table_position=10), away=make_team(team_id=2, table_position=2))
    assert check_5_league_gap(ctx).passed is False  # home is lower, not higher


def test_check_7_attack_vs_defence():
    ctx = make_ctx(home=make_team(goals_for_avg=3.2), away=make_team(team_id=2, goals_against_avg=3.1))
    assert check_7_attack_vs_defence_split(ctx).passed is True
    ctx = make_ctx(home=make_team(goals_for_avg=2.0), away=make_team(team_id=2, goals_against_avg=3.1))
    assert check_7_attack_vs_defence_split(ctx).passed is False


def test_check_8_xg_na_when_missing():
    ctx = make_ctx(home=make_team(xg_for_avg=None))
    assert check_8_expected_goals(ctx).passed is None


def test_check_9_h2h():
    ctx = make_ctx(h2h_totals=[3, 3, 4])
    assert check_9_h2h_over25(ctx).passed is True
    ctx = make_ctx(h2h_totals=[3, 1, 4])
    assert check_9_h2h_over25(ctx).passed is False
    ctx = make_ctx(h2h_totals=[3, 3])
    assert check_9_h2h_over25(ctx).passed is None


def test_check_10_recent_form():
    over_matches = [RecentMatch(i, "2025-01-01", 2, 1, 99) for i in range(5)]  # 3 goals each -> over
    ctx = make_ctx(
        home=make_team(recent_matches=over_matches),
        away=make_team(team_id=2, recent_matches=over_matches),
    )
    assert check_10_recent_form_over25(ctx).passed is True

    under_matches = [RecentMatch(i, "2025-01-01", 1, 0, 99) for i in range(5)]  # 1 goal each -> under
    ctx = make_ctx(
        home=make_team(recent_matches=under_matches),
        away=make_team(team_id=2, recent_matches=under_matches),
    )
    assert check_10_recent_form_over25(ctx).passed is False


def test_check_11_vs_league_average():
    ctx = make_ctx(
        home=make_team(goals_for_avg=2.0), away=make_team(team_id=2, goals_for_avg=2.0),
        home_league_avg_goals=1.5, away_league_avg_goals=1.5,
    )
    assert check_11_vs_league_average(ctx).passed is True
    ctx = make_ctx(
        home=make_team(goals_for_avg=1.0), home_league_avg_goals=1.5, away_league_avg_goals=1.5,
    )
    assert check_11_vs_league_average(ctx).passed is False


def test_key_players_missing_unknown_when_no_data():
    home = make_team(injuries=None)
    away = make_team(team_id=2, injuries=[])
    assert key_players_missing(home, away) == "Unknown"


def test_key_players_missing_flags_key_positions():
    home = make_team(injuries=[{"player": {"name": "A. Keeper", "type": "Goalkeeper", "reason": "Injury"}}])
    away = make_team(team_id=2, injuries=[])
    result = key_players_missing(home, away)
    assert "A. Keeper" in result
    assert "Goalkeeper" in result


def test_context_notes_relegation_six_pointer():
    home = make_team(table_position=18, is_relegation_zone=True)
    away = make_team(team_id=2, table_position=19, is_relegation_zone=True)
    ctx = make_ctx(home=home, away=away)
    notes = context_notes(ctx)
    assert "relegation" in notes.lower()


if __name__ == "__main__":
    # Allow running without pytest installed.
    failures = 0
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for test_fn in tests:
        try:
            test_fn()
            print(f"PASS {test_fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test_fn.__name__}: {exc}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed")
