"""
Fixture-fetching layer: scans the next N days worldwide for not-yet-started
fixtures. API-Football's /fixtures endpoint only reliably returns "all
matches worldwide" when queried one calendar date at a time (the from/to
range parameters are documented as needing to be paired with a league or
team filter), so we loop over each date in the window instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, date as date_cls

from api_client import ApiFootballClient

log = logging.getLogger("over25.fixtures")

# Fixture statuses that mean "hasn't kicked off yet" in API-Football's short codes.
NOT_STARTED_STATUSES = {"NS", "TBD"}


@dataclass
class Fixture:
    fixture_id: int
    date: str            # YYYY-MM-DD (local to api timezone)
    kick_off_time: str   # HH:MM
    league_id: int
    league_name: str
    country: str
    season: int
    competition_type: str  # "League" or "Cup"
    round: str
    home_team_id: int
    home_team_name: str
    away_team_id: int
    away_team_name: str

    @classmethod
    def from_api(cls, raw: dict) -> "Fixture":
        fx = raw["fixture"]
        league = raw["league"]
        teams = raw["teams"]
        kickoff = datetime.fromisoformat(fx["date"])
        return cls(
            fixture_id=fx["id"],
            date=kickoff.strftime("%Y-%m-%d"),
            kick_off_time=kickoff.strftime("%H:%M"),
            league_id=league["id"],
            league_name=league["name"],
            country=league["country"],
            season=league["season"],
            competition_type=league.get("type", "League"),
            round=league.get("round", ""),
            home_team_id=teams["home"]["id"],
            home_team_name=teams["home"]["name"],
            away_team_id=teams["away"]["id"],
            away_team_name=teams["away"]["name"],
        )


def fetch_fixtures_next_n_days(
    client: ApiFootballClient,
    days: int = 7,
    league_whitelist: list[str] | None = None,
    start_date: date_cls | None = None,
) -> list[Fixture]:
    """Fetch not-yet-started fixtures for the next `days` days (inclusive of today).

    `league_whitelist`, if given, is a list of league names or ids (as strings)
    to restrict to -- used for the Premier-League-only dry run before scaling
    up to worldwide scope.
    """
    start_date = start_date or datetime.now().date()
    all_fixtures: list[Fixture] = []

    whitelist_norm = None
    if league_whitelist:
        whitelist_norm = {str(item).strip().lower() for item in league_whitelist}

    for offset in range(days):
        day = start_date + timedelta(days=offset)
        day_str = day.strftime("%Y-%m-%d")
        log.info("Fetching fixtures for %s ...", day_str)
        try:
            raw_fixtures = client.fixtures_by_date(day_str)
        except Exception as exc:  # noqa: BLE001 - log and continue other days
            log.error("Failed to fetch fixtures for %s: %s", day_str, exc)
            continue

        for raw in raw_fixtures:
            status = raw.get("fixture", {}).get("status", {}).get("short", "")
            if status not in NOT_STARTED_STATUSES:
                continue
            fixture = Fixture.from_api(raw)
            if whitelist_norm is not None:
                if (
                    str(fixture.league_id) not in whitelist_norm
                    and fixture.league_name.strip().lower() not in whitelist_norm
                ):
                    continue
            all_fixtures.append(fixture)

    log.info("Found %d not-yet-started fixtures over the next %d day(s).", len(all_fixtures), days)
    return all_fixtures
