"""
The 15-point checklist, each as a small standalone function so they can be
unit-tested individually (see tests/test_checks.py).

Every check function takes a MatchContext and returns a CheckResult:
  passed: True / False / None (None == "N/A", not computable from available data)
  note:   short human-readable reason, mainly used for data_gaps text.

Checks 1-13 are the scored checklist (check 1 is also used as a hard gate --
see over25_predictor.py, which excludes the fixture entirely if check 1 fails).
Checks 14-15 are informational and are NOT booleans; see key_players_missing()
and context_notes() below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from team_stats import TeamSeasonStats

BTTS_THRESHOLD = 0.60
CLEAN_SHEET_THRESHOLD = 0.35
COMBINED_GOALS_THRESHOLD = 3.5
LEAGUE_GAP_MIN_PLACES = 5
SHOTS_ON_TARGET_THRESHOLD = 4.0
ATTACK_DEFENCE_THRESHOLD = 3.0
XG_THRESHOLD = 2.5
RECENT_FORM_OVER25_THRESHOLD = 0.60
EARLY_LATE_GOAL_THRESHOLD = 0.40


@dataclass
class MatchContext:
    home: TeamSeasonStats
    away: TeamSeasonStats
    min_games_played: int
    recent_form_games: int
    h2h_totals: list  # list[int] of total goals in each of the last H2H meetings, most recent first
    home_league_avg_goals: Optional[float]
    away_league_avg_goals: Optional[float]
    competition_type: str  # "League" or "Cup"


@dataclass
class CheckResult:
    passed: Optional[bool]
    note: str = ""


def check_1_sample_size(ctx: MatchContext) -> CheckResult:
    home_ok = (ctx.home.games_played or 0) >= ctx.min_games_played
    away_ok = (ctx.away.games_played or 0) >= ctx.min_games_played
    if home_ok and away_ok:
        return CheckResult(True)
    return CheckResult(
        False,
        f"insufficient games played (home={ctx.home.games_played}, away={ctx.away.games_played}, "
        f"need >= {ctx.min_games_played})",
    )


def check_2_btts_rate(ctx: MatchContext) -> CheckResult:
    if ctx.home.btts_rate is None or ctx.away.btts_rate is None:
        return CheckResult(None, "BTTS rate not computable for one or both teams (no recent match data)")
    passed = ctx.home.btts_rate > BTTS_THRESHOLD and ctx.away.btts_rate > BTTS_THRESHOLD
    return CheckResult(passed, f"home_btts={ctx.home.btts_rate}, away_btts={ctx.away.btts_rate}")


def check_3_clean_sheet_rate(ctx: MatchContext) -> CheckResult:
    if ctx.home.clean_sheet_rate is None or ctx.away.clean_sheet_rate is None:
        return CheckResult(None, "clean sheet rate not available for one or both teams")
    passed = ctx.home.clean_sheet_rate < CLEAN_SHEET_THRESHOLD and ctx.away.clean_sheet_rate < CLEAN_SHEET_THRESHOLD
    return CheckResult(passed, f"home_cs={ctx.home.clean_sheet_rate}, away_cs={ctx.away.clean_sheet_rate}")


def check_4_combined_goals_per_game(ctx: MatchContext) -> CheckResult:
    if ctx.home.goals_for_avg is None or ctx.away.goals_for_avg is None:
        return CheckResult(None, "goals-per-game average not available for one or both teams")
    combined = ctx.home.goals_for_avg + ctx.away.goals_for_avg
    return CheckResult(combined > COMBINED_GOALS_THRESHOLD, f"combined_gpg={round(combined, 2)}")


def check_5_league_gap(ctx: MatchContext) -> CheckResult:
    if ctx.home.table_position is None or ctx.away.table_position is None:
        return CheckResult(None, "table position not available (cup tie or missing standings)")
    gap = ctx.away.table_position - ctx.home.table_position
    passed = ctx.home.table_position < ctx.away.table_position and gap >= LEAGUE_GAP_MIN_PLACES
    return CheckResult(passed, f"home_pos={ctx.home.table_position}, away_pos={ctx.away.table_position}, gap={gap}")


def check_6_shots_on_target(ctx: MatchContext) -> CheckResult:
    if ctx.home.shots_on_target_avg is None or ctx.away.shots_on_target_avg is None:
        return CheckResult(None, "shots-on-target average not provided by API for one or both teams")
    passed = ctx.home.shots_on_target_avg > SHOTS_ON_TARGET_THRESHOLD and ctx.away.shots_on_target_avg > SHOTS_ON_TARGET_THRESHOLD
    return CheckResult(passed, f"home_sot={ctx.home.shots_on_target_avg}, away_sot={ctx.away.shots_on_target_avg}")


def check_7_attack_vs_defence_split(ctx: MatchContext) -> CheckResult:
    if ctx.home.goals_for_avg is None or ctx.away.goals_against_avg is None:
        return CheckResult(None, "goals-for/against average not available for home/away team")
    passed = ctx.home.goals_for_avg > ATTACK_DEFENCE_THRESHOLD and ctx.away.goals_against_avg > ATTACK_DEFENCE_THRESHOLD
    return CheckResult(
        passed, f"home_gf_avg={ctx.home.goals_for_avg}, away_ga_avg={ctx.away.goals_against_avg}"
    )


def check_8_expected_goals(ctx: MatchContext) -> CheckResult:
    """Approximation, clearly flagged: combined expected-goals estimate for the
    match = average of (home xG-for + home xGA + away xG-for + away xGA) / 2.
    xG is only available from API-Football for a subset of top leagues/seasons;
    N/A everywhere else rather than guessed."""
    vals = [ctx.home.xg_for_avg, ctx.home.xga_avg, ctx.away.xg_for_avg, ctx.away.xga_avg]
    if any(v is None for v in vals):
        return CheckResult(None, "xG data not available from API for this league/these teams")
    combined = sum(vals) / 2
    return CheckResult(combined > XG_THRESHOLD, f"combined_xg_estimate={round(combined, 2)} (approximation)")


def check_9_h2h_over25(ctx: MatchContext) -> CheckResult:
    if len(ctx.h2h_totals) < 3:
        return CheckResult(None, f"fewer than 3 head-to-head meetings on record ({len(ctx.h2h_totals)} found)")
    last3 = ctx.h2h_totals[:3]
    passed = all(total > 2.5 for total in last3)
    return CheckResult(passed, f"last3_h2h_totals={last3}")


def check_10_recent_form_over25(ctx: MatchContext) -> CheckResult:
    home_last = ctx.home.last_n(ctx.recent_form_games)
    away_last = ctx.away.last_n(ctx.recent_form_games)
    if len(home_last) < ctx.recent_form_games or len(away_last) < ctx.recent_form_games:
        return CheckResult(
            None,
            f"fewer than {ctx.recent_form_games} recent completed matches "
            f"(home={len(home_last)}, away={len(away_last)})",
        )
    home_rate = sum(1 for m in home_last if m.over_2_5) / len(home_last)
    away_rate = sum(1 for m in away_last if m.over_2_5) / len(away_last)
    passed = home_rate >= RECENT_FORM_OVER25_THRESHOLD and away_rate >= RECENT_FORM_OVER25_THRESHOLD
    return CheckResult(passed, f"home_rate={round(home_rate, 2)}, away_rate={round(away_rate, 2)}")


def check_11_vs_league_average(ctx: MatchContext) -> CheckResult:
    if (
        ctx.home.goals_for_avg is None or ctx.away.goals_for_avg is None
        or ctx.home_league_avg_goals is None or ctx.away_league_avg_goals is None
    ):
        return CheckResult(None, "team or league average goals-per-game not available")
    passed = ctx.home.goals_for_avg > ctx.home_league_avg_goals and ctx.away.goals_for_avg > ctx.away_league_avg_goals
    return CheckResult(
        passed,
        f"home_gpg={ctx.home.goals_for_avg} vs league_avg={ctx.home_league_avg_goals}; "
        f"away_gpg={ctx.away.goals_for_avg} vs league_avg={ctx.away_league_avg_goals}",
    )


def check_12_early_goals(ctx: MatchContext) -> CheckResult:
    if ctx.home.early_goal_rate is None or ctx.away.early_goal_rate is None:
        return CheckResult(
            None,
            f"insufficient match-event data for early-goal timing "
            f"(home_n={ctx.home.early_goal_sample_size}, away_n={ctx.away.early_goal_sample_size})",
        )
    passed = ctx.home.early_goal_rate >= EARLY_LATE_GOAL_THRESHOLD and ctx.away.early_goal_rate >= EARLY_LATE_GOAL_THRESHOLD
    return CheckResult(
        passed,
        f"home_early_rate={ctx.home.early_goal_rate} (n={ctx.home.early_goal_sample_size}), "
        f"away_early_rate={ctx.away.early_goal_rate} (n={ctx.away.early_goal_sample_size})",
    )


def check_13_late_goals(ctx: MatchContext) -> CheckResult:
    if ctx.home.late_goal_rate is None or ctx.away.late_goal_rate is None:
        return CheckResult(
            None,
            f"insufficient match-event data for late-goal timing "
            f"(home_n={ctx.home.late_goal_sample_size}, away_n={ctx.away.late_goal_sample_size})",
        )
    passed = ctx.home.late_goal_rate >= EARLY_LATE_GOAL_THRESHOLD and ctx.away.late_goal_rate >= EARLY_LATE_GOAL_THRESHOLD
    return CheckResult(
        passed,
        f"home_late_rate={ctx.home.late_goal_rate} (n={ctx.home.late_goal_sample_size}), "
        f"away_late_rate={ctx.away.late_goal_rate} (n={ctx.away.late_goal_sample_size})",
    )


# Ordered list of the 13 scored checks -- used by scoring.py to build columns
# check_1 .. check_13 and compute checks_passed / checks_computable generically.
SCORED_CHECKS = [
    ("check_1", check_1_sample_size),
    ("check_2", check_2_btts_rate),
    ("check_3", check_3_clean_sheet_rate),
    ("check_4", check_4_combined_goals_per_game),
    ("check_5", check_5_league_gap),
    ("check_6", check_6_shots_on_target),
    ("check_7", check_7_attack_vs_defence_split),
    ("check_8", check_8_expected_goals),
    ("check_9", check_9_h2h_over25),
    ("check_10", check_10_recent_form_over25),
    ("check_11", check_11_vs_league_average),
    ("check_12", check_12_early_goals),
    ("check_13", check_13_late_goals),
]

KEY_POSITIONS = {"Goalkeeper", "Defender"}


def key_players_missing(home: TeamSeasonStats, away: TeamSeasonStats) -> str:
    """Check 14. Returns 'Unknown' if injury data wasn't available for either
    team, otherwise a semicolon-separated summary (or 'None reported')."""
    if home.injuries is None or away.injuries is None:
        return "Unknown"

    parts = []
    for label, stats in (("HOME", home), ("AWAY", away)):
        flagged = []
        for entry in stats.injuries or []:
            player = entry.get("player", {})
            name = player.get("name", "Unknown player")
            position = (player.get("type") or player.get("position") or "").strip()
            reason = player.get("reason", "")
            if position in KEY_POSITIONS or not position:
                flagged.append(f"{name}{f' ({position})' if position else ''}{f' - {reason}' if reason else ''}")
        if flagged:
            parts.append(f"{label} ({stats.team_name}): " + "; ".join(flagged))

    return " | ".join(parts) if parts else "None reported"


def context_notes(ctx: MatchContext) -> str:
    """Check 15. Free text, derived only from what the data actually shows --
    never invented."""
    notes = []

    if ctx.competition_type and ctx.competition_type.lower() == "cup":
        notes.append("Cup match")

    for label, stats in (("Home", ctx.home), ("Away", ctx.away)):
        if stats.is_relegation_zone:
            notes.append(f"{label} team ({stats.team_name}) is in the relegation zone")

    if (
        ctx.home.is_relegation_zone
        and ctx.away.is_relegation_zone
        and ctx.home.table_position is not None
        and ctx.away.table_position is not None
        and abs(ctx.home.table_position - ctx.away.table_position) <= 3
    ):
        notes.append("Possible relegation six-pointer (both teams in/near drop zone, close in the table)")

    if not notes:
        return ""
    return "; ".join(notes)
