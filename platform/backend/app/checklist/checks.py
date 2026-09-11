"""The 13 scored checklist items as pure functions — no database access,
each testable in isolation with plain numbers. Every function returns
`True`, `False`, or `None` ("N/A" — not enough data to evaluate this
check, never guessed as either True or False).

CHECK_LABELS documents the full 1-15 item numbering (13 scored + 2
informational) against each item's short name, so the mapping from the
original checklist spec to this codebase's column/field names is in one
place rather than implied.

Two checks needed an interpretation call where the original checklist
wording was ambiguous against what data is actually available — both
documented on the function itself, not left implicit:
  - check 8 (xG): summed across both teams' xG-for and xG-against, since
    "xG for both teams in this matchup" doesn't specify per-team vs
    combined.
  - check 11 (vs league average): compared each team against that
    league's *venue-specific* average (home team vs league home-goals
    average, away team vs league away-goals average) rather than a single
    combined figure, since match_features already stores those two
    separately and it's a fairer comparison than the alternative of
    comparing every team's raw scoring rate to one blended number.
"""

from __future__ import annotations

CHECK_LABELS: dict[int, str] = {
    1: "sample_size",
    2: "btts_rate",
    3: "clean_sheet_rate",
    4: "combined_goals",
    5: "league_gap",
    6: "shots_on_target",
    7: "attack_defence_split",
    8: "xg",
    9: "h2h",
    10: "recent_form",
    11: "vs_league_avg",
    12: "early_goals",
    13: "late_goals",
    14: "key_players_missing",  # informational, not scored
    15: "context_notes",  # informational, not scored
}


def check_sample_size(home_games_played: int, away_games_played: int, *, min_games: int = 5) -> bool:
    """Always computable (never N/A) - a fixture failing this is excluded
    entirely by the service layer, per spec, rather than scored."""
    return home_games_played >= min_games and away_games_played >= min_games


def check_btts_rate(home_btts_pct: float | None, away_btts_pct: float | None, *, threshold: float = 0.60) -> bool | None:
    if home_btts_pct is None or away_btts_pct is None:
        return None
    return home_btts_pct > threshold and away_btts_pct > threshold


def check_clean_sheet_rate(
    home_clean_sheet_pct: float | None, away_clean_sheet_pct: float | None, *, threshold: float = 0.35
) -> bool | None:
    if home_clean_sheet_pct is None or away_clean_sheet_pct is None:
        return None
    return home_clean_sheet_pct < threshold and away_clean_sheet_pct < threshold


def check_combined_goals(
    home_goals_per_game: float | None, away_goals_per_game: float | None, *, threshold: float = 3.5
) -> bool | None:
    if home_goals_per_game is None or away_goals_per_game is None:
        return None
    return (home_goals_per_game + away_goals_per_game) > threshold


def check_league_gap(home_position: int | None, away_position: int | None, *, min_gap: int = 5) -> bool | None:
    """Position 1 = top of the table. Home team must be higher-placed
    (lower position number) AND the gap must be at least `min_gap`."""
    if home_position is None or away_position is None:
        return None
    return home_position < away_position and (away_position - home_position) >= min_gap


def check_shots_on_target(
    home_sot_avg: float | None, away_sot_avg: float | None, *, threshold: float = 4.0
) -> bool | None:
    if home_sot_avg is None or away_sot_avg is None:
        return None
    return home_sot_avg > threshold and away_sot_avg > threshold


def check_attack_defence_split(
    home_goals_for_avg: float | None, away_goals_against_avg: float | None, *, threshold: float = 3.0
) -> bool | None:
    """Home team's own scoring average AND away team's own conceding
    average, both over the threshold - as literally specified, not each
    team's overall attack/defence balance."""
    if home_goals_for_avg is None or away_goals_against_avg is None:
        return None
    return home_goals_for_avg > threshold and away_goals_against_avg > threshold


def check_combined_xg(
    home_xg_for: float | None,
    home_xg_against: float | None,
    away_xg_for: float | None,
    away_xg_against: float | None,
    *,
    threshold: float = 2.5,
) -> bool | None:
    values = (home_xg_for, home_xg_against, away_xg_for, away_xg_against)
    if any(v is None for v in values):
        return None
    return sum(values) > threshold


def check_h2h_last3(h2h_last3_total_goals: list[int] | None) -> bool | None:
    """`h2h_last3_total_goals` must contain exactly the last 3 meetings'
    total goals (most-recent-first or in any order - only membership
    matters), or fewer than 3 exist and this stays N/A."""
    if h2h_last3_total_goals is None or len(h2h_last3_total_goals) < 3:
        return None
    return all(total_goals > 2 for total_goals in h2h_last3_total_goals[:3])


def check_recent_form(
    home_over25_last5_pct: float | None, away_over25_last5_pct: float | None, *, threshold: float = 0.60
) -> bool | None:
    if home_over25_last5_pct is None or away_over25_last5_pct is None:
        return None
    return home_over25_last5_pct >= threshold and away_over25_last5_pct >= threshold


def check_vs_league_average(
    home_goals_per_game: float | None,
    away_goals_per_game: float | None,
    league_home_goals_avg: float | None,
    league_away_goals_avg: float | None,
) -> bool | None:
    if None in (home_goals_per_game, away_goals_per_game, league_home_goals_avg, league_away_goals_avg):
        return None
    return home_goals_per_game > league_home_goals_avg and away_goals_per_game > league_away_goals_avg


def check_early_goals(
    home_early_goal_pct: float | None, away_early_goal_pct: float | None, *, threshold: float = 0.40
) -> bool | None:
    """Always N/A today - no goal-timing/events data is ingested by this
    platform yet (a real schema gap, not a bug); kept as a real function
    so it's a one-line change once that data exists, rather than a
    hardcoded None in the service layer."""
    if home_early_goal_pct is None or away_early_goal_pct is None:
        return None
    return home_early_goal_pct >= threshold and away_early_goal_pct >= threshold


def check_late_goals(
    home_late_goal_pct: float | None, away_late_goal_pct: float | None, *, threshold: float = 0.40
) -> bool | None:
    """Same as check_early_goals - always N/A until goal-timing data exists."""
    if home_late_goal_pct is None or away_late_goal_pct is None:
        return None
    return home_late_goal_pct >= threshold and away_late_goal_pct >= threshold
