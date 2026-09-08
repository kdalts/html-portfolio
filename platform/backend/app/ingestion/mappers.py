"""Pure functions mapping raw Sportmonks Football v3 JSON payloads to the
column dicts our repository layer upserts. No I/O, no database, no
network — every function here takes plain dicts in and returns plain
dicts (or lists of dicts) out, which is what makes them fast and reliable
to unit test with canned payloads.

Payload shape assumptions (fixture objects fetched with
`include=participants;scores;state;league;season[;statistics;predictions;odds]`):

  fixture: {
    "id": int, "league_id": int, "season_id": int,
    "starting_at": "YYYY-MM-DD HH:MM:SS" (UTC), "starting_at_timestamp": int,
    "participants": [{"id": int, "name": str, "meta": {"location": "home"|"away"}}, ...],
    "scores": [{"description": "CURRENT", "participant_id": int, "score": {"goals": int}}, ...],
    "state": {"short_name": str},
    "league": {...}, "season": {...},
    "statistics": [{"type_id": int, "participant_id": int, "data": {"value": ...}}, ...],
    "predictions": [{"type_id": int, "predictions": {"yes": float, "no": float}}, ...],
    "odds": [{"market_id": int, "bookmaker_id": int, "label": "Over"|"Under",
               "total": "2.5", "value": "1.85"}, ...],
  }

These shapes are standard Sportmonks v3 conventions but have not been
validated against a live token (see docs/DATABASE.md and the Phase 2/3
"remaining risks" notes) — treat field names as best-effort until checked
against real responses.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from app.db.models.fixtures import VALID_FIXTURE_STATUSES
from app.ingestion.errors import MappingError

# Sportmonks fixture state short_names we've seen documented, mapped onto
# our compact status set. Anything not in VALID_FIXTURE_STATUSES already
# and not found here falls back to "NS" with a logged warning (status is
# informational only; it never feeds the over_2_5 target label, which is
# derived solely from home_goals/away_goals by the database).
STATE_SHORT_NAME_TO_STATUS = {
    "INPLAY_1ST_HALF": "LIVE",
    "INPLAY_2ND_HALF": "LIVE",
    "FT_PEN": "PEN",
    "POSTPONED": "POSTP",
    "CANCELLED": "CANC",
    "ABANDONED": "ABAN",
    "SUSPENDED": "SUSP",
    "INTERRUPTED": "SUSP",
    "TBA": "TBD",
}


def parse_kickoff(raw_fixture: dict) -> datetime:
    ts = raw_fixture.get("starting_at_timestamp")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    raw = raw_fixture.get("starting_at")
    if not raw:
        raise MappingError("fixture is missing starting_at / starting_at_timestamp")
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise MappingError(f"unparseable starting_at value: {raw!r}") from exc


def parse_date_only(raw: str | None) -> date | None:
    if not raw:
        return None
    return datetime.strptime(raw[:10], "%Y-%m-%d").date()


def map_fixture_status(raw_fixture: dict, *, logger: logging.Logger | None = None) -> str:
    state = raw_fixture.get("state") or {}
    short_name = state.get("short_name") or state.get("state")
    if not short_name:
        return "NS"
    short_name = short_name.upper()
    if short_name in VALID_FIXTURE_STATUSES:
        return short_name
    mapped = STATE_SHORT_NAME_TO_STATUS.get(short_name)
    if mapped:
        return mapped
    if logger:
        logger.warning("Unrecognized Sportmonks fixture state %r; defaulting to NS", short_name)
    return "NS"


def _extract_participants(raw_fixture: dict) -> tuple[int, int]:
    participants = raw_fixture.get("participants") or []
    home_id = away_id = None
    for participant in participants:
        location = (participant.get("meta") or {}).get("location")
        if location == "home":
            home_id = participant.get("id")
        elif location == "away":
            away_id = participant.get("id")
    if home_id is None or away_id is None:
        raise MappingError("fixture participants missing a home and/or away team")
    return home_id, away_id


def _extract_goals(
    raw_fixture: dict, home_team_id: int, away_team_id: int
) -> tuple[int | None, int | None]:
    scores = raw_fixture.get("scores") or []
    home_goals = away_goals = None
    for entry in scores:
        if (entry.get("description") or "").upper() != "CURRENT":
            continue
        goals = (entry.get("score") or {}).get("goals")
        participant_id = entry.get("participant_id")
        if participant_id == home_team_id:
            home_goals = goals
        elif participant_id == away_team_id:
            away_goals = goals
    return home_goals, away_goals


def map_fixture(raw_fixture: dict, *, logger: logging.Logger | None = None) -> dict[str, Any]:
    fixture_id = raw_fixture.get("id")
    league_id = raw_fixture.get("league_id")
    season_id = raw_fixture.get("season_id")
    if fixture_id is None or league_id is None or season_id is None:
        raise MappingError("fixture missing id/league_id/season_id")

    home_team_id, away_team_id = _extract_participants(raw_fixture)
    kickoff = parse_kickoff(raw_fixture)
    home_goals, away_goals = _extract_goals(raw_fixture, home_team_id, away_team_id)
    status = map_fixture_status(raw_fixture, logger=logger)

    return {
        "id": fixture_id,
        "league_id": league_id,
        "season_id": season_id,
        "kickoff": kickoff,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "status": status,
    }


def map_league(raw_league: dict) -> dict[str, Any]:
    league_id = raw_league.get("id")
    if league_id is None:
        raise MappingError("league missing id")
    country = raw_league.get("country") or {}
    return {
        "id": league_id,
        "name": raw_league.get("name") or f"League {league_id}",
        "country_id": raw_league.get("country_id"),
        "country_name": country.get("name"),
        "is_active": bool(raw_league.get("active", True)),
    }


def map_team(raw_team: dict) -> dict[str, Any]:
    team_id = raw_team.get("id")
    if team_id is None:
        raise MappingError("team missing id")
    country = raw_team.get("country") or {}
    return {
        "id": team_id,
        "name": raw_team.get("name") or f"Team {team_id}",
        "short_code": raw_team.get("short_code"),
        "country_id": raw_team.get("country_id"),
        "country_name": country.get("name"),
        "founded": raw_team.get("founded"),
        "logo_url": raw_team.get("image_path"),
    }


def map_season(raw_season: dict) -> dict[str, Any]:
    season_id = raw_season.get("id")
    league_id = raw_season.get("league_id")
    if season_id is None or league_id is None:
        raise MappingError("season missing id/league_id")
    return {
        "id": season_id,
        "league_id": league_id,
        "name": raw_season.get("name") or f"Season {season_id}",
        "start_date": parse_date_only(raw_season.get("starting_at")),
        "end_date": parse_date_only(raw_season.get("ending_at")),
        "is_current": bool(raw_season.get("is_current", False)),
    }


def map_match_statistics(raw_fixture: dict, stat_type_ids: dict[str, int | None]) -> list[dict[str, Any]]:
    """stat_type_ids: our column name -> Sportmonks type_id (see
    sportmonks_reference.STATISTIC_TYPE_IDS). Entries whose type_id is
    None (not yet configured) are simply never matched — this degrades
    gracefully to "no stats extracted" rather than raising."""
    fixture_id = raw_fixture.get("id")
    type_id_to_stat = {v: k for k, v in stat_type_ids.items() if v is not None}
    per_team: dict[int, dict[str, Any]] = {}
    for entry in raw_fixture.get("statistics") or []:
        stat_name = type_id_to_stat.get(entry.get("type_id"))
        team_id = entry.get("participant_id")
        if stat_name is None or team_id is None:
            continue
        value = (entry.get("data") or {}).get("value")
        row = per_team.setdefault(team_id, {"fixture_id": fixture_id, "team_id": team_id})
        row[stat_name] = value
    return list(per_team.values())


def map_match_xg(raw_fixture: dict, xg_type_id: int | None, *, source: str = "sportmonks") -> list[dict[str, Any]]:
    if xg_type_id is None:
        return []
    fixture_id = raw_fixture.get("id")
    rows = []
    for entry in raw_fixture.get("statistics") or []:
        if entry.get("type_id") != xg_type_id:
            continue
        team_id = entry.get("participant_id")
        if team_id is None:
            continue
        rows.append(
            {
                "fixture_id": fixture_id,
                "team_id": team_id,
                "xg": (entry.get("data") or {}).get("value"),
                "source": source,
            }
        )
    return rows


def map_sportmonks_prediction(
    raw_fixture: dict,
    *,
    over_2_5_type_id: int | None,
    btts_type_id: int | None = None,
    retrieved_at: datetime,
) -> dict[str, Any] | None:
    """Returns None if neither the over/under nor BTTS market was found
    (nothing worth storing), rather than an all-null row."""
    if over_2_5_type_id is None and btts_type_id is None:
        return None
    fixture_id = raw_fixture.get("id")
    over_2_5_probability = None
    btts_probability = None
    raw_payload: dict[str, Any] = {}
    for entry in raw_fixture.get("predictions") or []:
        type_id = entry.get("type_id")
        prediction = entry.get("predictions") or {}
        if over_2_5_type_id is not None and type_id == over_2_5_type_id:
            yes = prediction.get("yes")
            over_2_5_probability = (yes / 100.0) if isinstance(yes, (int, float)) else None
            raw_payload["over_2_5"] = prediction
        elif btts_type_id is not None and type_id == btts_type_id:
            yes = prediction.get("yes")
            btts_probability = (yes / 100.0) if isinstance(yes, (int, float)) else None
            raw_payload["btts"] = prediction

    if over_2_5_probability is None and btts_probability is None:
        return None

    return {
        "fixture_id": fixture_id,
        "over_2_5_probability": over_2_5_probability,
        "btts_probability": btts_probability,
        "predicted_home_goals": None,
        "predicted_away_goals": None,
        "raw_payload": raw_payload or None,
        "retrieved_at": retrieved_at,
    }


def map_odds(
    raw_fixture: dict,
    *,
    market_id: int | None,
    retrieved_at: datetime,
    total_line: str = "2.5",
    bookmaker_names: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    if market_id is None:
        return []
    fixture_id = raw_fixture.get("id")
    bookmaker_names = bookmaker_names or {}
    per_bookmaker: dict[int, dict[str, float]] = {}

    for entry in raw_fixture.get("odds") or []:
        if entry.get("market_id") != market_id:
            continue
        if str(entry.get("total")) != total_line:
            continue
        bookmaker_id = entry.get("bookmaker_id")
        if bookmaker_id is None:
            continue
        label = (entry.get("label") or "").upper()
        try:
            value = float(entry.get("value"))
        except (TypeError, ValueError):
            continue
        bucket = per_bookmaker.setdefault(bookmaker_id, {})
        if label == "OVER":
            bucket["over_odds"] = value
        elif label == "UNDER":
            bucket["under_odds"] = value

    rows = []
    for bookmaker_id, prices in per_bookmaker.items():
        if "over_odds" not in prices or "under_odds" not in prices:
            continue  # only store complete Over/Under pairs
        rows.append(
            {
                "fixture_id": fixture_id,
                "bookmaker": bookmaker_names.get(bookmaker_id, str(bookmaker_id)),
                "market": "over_under_2_5",
                "over_odds": prices["over_odds"],
                "under_odds": prices["under_odds"],
                "retrieved_at": retrieved_at,
            }
        )
    return rows
