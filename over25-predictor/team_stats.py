"""
Stats-fetching layer: builds a TeamSeasonStats bundle for one team in the
context of one league/season, plus league-wide and head-to-head data.

Design goal: fetch each expensive thing (team fixture list, standings,
injuries) at most once per team per run, and cache it (see api_client.py)
so re-running the script the same day doesn't re-spend API quota.

Where API-Football doesn't have the data (xG for most leagues, injuries for
smaller leagues), fields are left as None and the checks/scoring layer turns
that into "N/A" + a data_gaps note -- we never invent a number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from api_client import ApiFootballClient
from config import SETTINGS

log = logging.getLogger("over25.team_stats")

# Treat kickoff-minute < 15 as "first 15 minutes", and elapsed >= 75 as
# "last 15 minutes" (75-90 + stoppage, i.e. extra["elapsed_plus"] on top of
# elapsed==90 is also captured since elapsed itself already reaches 90+).
EARLY_GOAL_CUTOFF_MIN = 15
LATE_GOAL_CUTOFF_MIN = 75


@dataclass
class RecentMatch:
    fixture_id: int
    date: str
    goals_for: int
    goals_against: int
    opponent_id: int

    @property
    def total_goals(self) -> int:
        return self.goals_for + self.goals_against

    @property
    def over_2_5(self) -> bool:
        return self.total_goals > 2.5

    @property
    def btts(self) -> bool:
        return self.goals_for > 0 and self.goals_against > 0


@dataclass
class TeamSeasonStats:
    team_id: int
    team_name: str
    league_id: int
    season: int

    games_played: Optional[int] = None
    goals_for_avg: Optional[float] = None
    goals_against_avg: Optional[float] = None
    clean_sheet_rate: Optional[float] = None
    btts_rate: Optional[float] = None
    shots_on_target_avg: Optional[float] = None

    recent_matches: list = field(default_factory=list)  # list[RecentMatch], most recent first

    xg_for_avg: Optional[float] = None
    xga_avg: Optional[float] = None
    xg_sample_size: int = 0

    early_goal_rate: Optional[float] = None
    early_goal_sample_size: int = 0
    late_goal_rate: Optional[float] = None
    late_goal_sample_size: int = 0

    table_position: Optional[int] = None
    league_size: Optional[int] = None
    is_relegation_zone: Optional[bool] = None

    injuries: Optional[list] = None  # None = "Unknown" (endpoint unsupported/empty)

    data_gaps: list = field(default_factory=list)

    def last_n(self, n: int) -> list:
        return self.recent_matches[:n]


def _safe_avg(numerator, denominator):
    if not denominator:
        return None
    try:
        return round(numerator / denominator, 3)
    except (TypeError, ZeroDivisionError):
        return None


def build_team_recent_matches(client: ApiFootballClient, team_id: int, season: int, last: int) -> list:
    raw = client.team_fixtures(team_id, season=season, last=last)
    matches = []
    for item in raw:
        status = item.get("fixture", {}).get("status", {}).get("short")
        if status != "FT":  # only completed matches count for historical stats
            continue
        teams = item["teams"]
        goals = item["goals"]
        if teams["home"]["id"] == team_id:
            gf, ga = goals["home"], goals["away"]
            opponent_id = teams["away"]["id"]
        else:
            gf, ga = goals["away"], goals["home"]
            opponent_id = teams["home"]["id"]
        if gf is None or ga is None:
            continue
        matches.append(
            RecentMatch(
                fixture_id=item["fixture"]["id"],
                date=item["fixture"]["date"][:10],
                goals_for=gf,
                goals_against=ga,
                opponent_id=opponent_id,
            )
        )
    # API-Football returns most-recent-last for `last=N`; normalise to most-recent-first.
    matches.sort(key=lambda m: m.date, reverse=True)
    return matches


def compute_btts_rate(matches: list) -> Optional[float]:
    if not matches:
        return None
    return round(sum(1 for m in matches if m.btts) / len(matches), 3)


def compute_early_late_goal_rates(
    client: ApiFootballClient, team_id: int, matches: list, min_sample: int
) -> tuple:
    """Returns (early_rate, early_n, late_rate, late_n). One /fixtures/events
    call per historical match -- this is the expensive part of checks 12/13,
    hence `matches` should already be capped to the configured lookback."""
    early_hits = 0
    late_hits = 0
    usable = 0

    for match in matches:
        try:
            events = client.fixture_events(match.fixture_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not fetch events for fixture %s: %s", match.fixture_id, exc)
            continue

        goal_events = [
            e for e in events
            if e.get("type") == "Goal"
            and e.get("team", {}).get("id") == team_id
            and e.get("detail") != "Missed Penalty"
        ]
        if not events:
            # No event data at all for this fixture (common for lower leagues) -- skip it.
            continue

        usable += 1
        scored_early = any((g.get("time", {}).get("elapsed") or 0) < EARLY_GOAL_CUTOFF_MIN for g in goal_events)
        scored_late = any((g.get("time", {}).get("elapsed") or 0) >= LATE_GOAL_CUTOFF_MIN for g in goal_events)
        if scored_early:
            early_hits += 1
        if scored_late:
            late_hits += 1

    if usable < min_sample:
        return None, usable, None, usable
    return round(early_hits / usable, 3), usable, round(late_hits / usable, 3), usable


def compute_xg_rates(client: ApiFootballClient, team_id: int, matches: list) -> tuple:
    """Best-effort xG: API-Football only exposes 'expected_goals' as a fixture
    statistic for a subset of top leagues/seasons. We average it across
    whatever historical matches actually carry the stat; if none do, we
    return (None, None, 0) rather than guessing."""
    xg_for_values = []
    xg_against_values = []

    for match in matches:
        try:
            stats = client.fixture_statistics(match.fixture_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not fetch fixture statistics for %s: %s", match.fixture_id, exc)
            continue

        for team_block in stats:
            block_team_id = team_block.get("team", {}).get("id")
            xg_value = None
            for stat in team_block.get("statistics", []):
                if stat.get("type", "").lower() in ("expected_goals", "xg"):
                    try:
                        xg_value = float(stat.get("value"))
                    except (TypeError, ValueError):
                        xg_value = None
            if xg_value is None:
                continue
            if block_team_id == team_id:
                xg_for_values.append(xg_value)
            else:
                xg_against_values.append(xg_value)

    xg_for_avg = _safe_avg(sum(xg_for_values), len(xg_for_values)) if xg_for_values else None
    xga_avg = _safe_avg(sum(xg_against_values), len(xg_against_values)) if xg_against_values else None
    sample = min(len(xg_for_values), len(xg_against_values))
    return xg_for_avg, xga_avg, sample


def fetch_team_season_stats(
    client: ApiFootballClient,
    team_id: int,
    team_name: str,
    league_id: int,
    season: int,
    settings=SETTINGS,
) -> TeamSeasonStats:
    stats = TeamSeasonStats(team_id=team_id, team_name=team_name, league_id=league_id, season=season)

    raw_stats = client.team_statistics(team_id, league_id, season)
    fixtures_block = raw_stats.get("fixtures", {}) if raw_stats else {}
    goals_block = raw_stats.get("goals", {}) if raw_stats else {}
    clean_sheet_block = raw_stats.get("clean_sheet", {}) if raw_stats else {}

    played_total = fixtures_block.get("played", {}).get("total")
    stats.games_played = played_total

    stats.goals_for_avg = _to_float(goals_block.get("for", {}).get("average", {}).get("total"))
    stats.goals_against_avg = _to_float(goals_block.get("against", {}).get("average", {}).get("total"))

    cs_total = clean_sheet_block.get("total")
    stats.clean_sheet_rate = _safe_avg(cs_total, played_total) if cs_total is not None else None

    shots_block = raw_stats.get("shots", {}) if raw_stats else {}
    stats.shots_on_target_avg = _to_float(shots_block.get("on", {}).get("average"))
    if stats.shots_on_target_avg is None:
        stats.data_gaps.append("shots on target average not provided by API for this team/league")

    # Recent matches (covers BTTS rate, combined-goals context, recent form,
    # and doubles as the base for the early/late-goal event lookups).
    lookback = max(settings.timing_lookback_games, settings.recent_form_games)
    matches = build_team_recent_matches(client, team_id, season, last=lookback)
    stats.recent_matches = matches
    stats.btts_rate = compute_btts_rate(matches)
    if stats.btts_rate is None:
        stats.data_gaps.append("no completed recent matches found for BTTS rate")

    # xG (best-effort, configurable off to save API calls)
    if settings.fetch_xg:
        xg_for, xga, xg_n = compute_xg_rates(client, team_id, matches[: settings.timing_lookback_games])
        stats.xg_for_avg, stats.xga_avg, stats.xg_sample_size = xg_for, xga, xg_n
        if xg_for is None or xga is None:
            stats.data_gaps.append("expected-goals (xG) stat not available from API for this team's league")
    else:
        stats.data_gaps.append("xG fetch disabled in config (FETCH_XG=false)")

    # Early / late goal timing (checks 12 & 13) -- expensive, capped by config.
    early_rate, early_n, late_rate, late_n = compute_early_late_goal_rates(
        client, team_id, matches[: settings.timing_lookback_games], settings.min_timing_sample
    )
    stats.early_goal_rate, stats.early_goal_sample_size = early_rate, early_n
    stats.late_goal_rate, stats.late_goal_sample_size = late_rate, late_n
    if early_rate is None:
        stats.data_gaps.append(
            f"insufficient match-event data for early/late goal timing "
            f"(usable matches: {early_n}/{len(matches[: settings.timing_lookback_games])})"
        )

    # Injuries (check 14) -- "Unknown" (None) when the league/endpoint has no data.
    if settings.fetch_injuries:
        try:
            injuries_raw = client.injuries(team_id, season)
            stats.injuries = injuries_raw if injuries_raw else []
            if not injuries_raw:
                # Ambiguous: could genuinely be zero injuries, or unsupported league.
                # We keep it as an empty list (not "Unknown") since the API call
                # succeeded; only a fetch failure below sets it to None/"Unknown".
                pass
        except Exception as exc:  # noqa: BLE001
            log.warning("Injuries fetch failed for team %s: %s", team_id, exc)
            stats.injuries = None
            stats.data_gaps.append("injuries endpoint unavailable/unsupported for this league -> Unknown")
    else:
        stats.injuries = None
        stats.data_gaps.append("injuries fetch disabled in config (FETCH_INJURIES=false)")

    return stats


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def attach_standings(client: ApiFootballClient, stats: TeamSeasonStats, league_id: int, season: int) -> None:
    """Fills in table_position / league_size / is_relegation_zone on `stats`."""
    try:
        groups = client.standings(league_id, season)
    except Exception as exc:  # noqa: BLE001
        log.warning("Standings fetch failed for league %s: %s", league_id, exc)
        stats.data_gaps.append("standings unavailable (cup competition or unsupported league)")
        return

    # standings is a list of groups (e.g. multiple groups in some cups); flatten.
    flat = [row for group in groups for row in group]
    if not flat:
        stats.data_gaps.append("standings unavailable (cup competition or unsupported league)")
        return

    stats.league_size = len(flat)
    for row in flat:
        if row.get("team", {}).get("id") == stats.team_id:
            stats.table_position = row.get("rank")
            description = (row.get("description") or "").lower()
            stats.is_relegation_zone = "relegation" in description
            break


def league_average_goals_per_game(client: ApiFootballClient, league_id: int, season: int) -> Optional[float]:
    """Average total goals per game across the whole league table, derived from
    standings (sum of goals-for across all teams / sum of games played)."""
    try:
        groups = client.standings(league_id, season)
    except Exception as exc:  # noqa: BLE001
        log.warning("Standings fetch failed for league average (league %s): %s", league_id, exc)
        return None

    flat = [row for group in groups for row in group]
    if not flat:
        return None

    total_goals = 0
    total_games = 0
    for row in flat:
        played = row.get("all", {}).get("played")
        goals_for = row.get("all", {}).get("goals", {}).get("for")
        if played and goals_for is not None:
            total_goals += goals_for
            total_games += played

    return _safe_avg(total_goals, total_games)
