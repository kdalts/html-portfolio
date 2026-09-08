from datetime import datetime, timezone

import pytest

from app.ingestion import mappers
from app.ingestion.errors import MappingError

FINISHED_FIXTURE = {
    "id": 18528480,
    "league_id": 8,
    "season_id": 19735,
    "starting_at": "2024-08-17 15:00:00",
    "participants": [
        {"id": 1, "name": "Home FC", "meta": {"location": "home"}},
        {"id": 2, "name": "Away FC", "meta": {"location": "away"}},
    ],
    "scores": [
        {"description": "1ST_HALF", "participant_id": 1, "score": {"goals": 1}},
        {"description": "CURRENT", "participant_id": 1, "score": {"goals": 2}},
        {"description": "CURRENT", "participant_id": 2, "score": {"goals": 1}},
    ],
    "state": {"short_name": "FT"},
    "league": {"id": 8, "name": "Premier League", "country_id": 462, "active": True},
    "season": {
        "id": 19735,
        "league_id": 8,
        "name": "2024/2025",
        "starting_at": "2024-08-10",
        "ending_at": "2025-05-25",
        "is_current": True,
    },
    "statistics": [
        {"type_id": 42, "participant_id": 1, "data": {"value": 15}},
        {"type_id": 42, "participant_id": 2, "data": {"value": 9}},
        {"type_id": 86, "participant_id": 1, "data": {"value": 1.8}},  # xg
        {"type_id": 86, "participant_id": 2, "data": {"value": 0.9}},
    ],
    "predictions": [
        {"type_id": 231, "predictions": {"yes": 62.5, "no": 37.5}},
    ],
    "odds": [
        {"market_id": 12, "bookmaker_id": 2, "label": "Over", "total": "2.5", "value": "1.85"},
        {"market_id": 12, "bookmaker_id": 2, "label": "Under", "total": "2.5", "value": "2.10"},
        {"market_id": 12, "bookmaker_id": 5, "label": "Over", "total": "2.5", "value": "1.90"},
        {"market_id": 12, "bookmaker_id": 5, "label": "Under", "total": "2.5", "value": "2.00"},
        {"market_id": 12, "bookmaker_id": 9, "label": "Over", "total": "3.5", "value": "3.20"},  # wrong line
    ],
}

UPCOMING_FIXTURE = {
    "id": 999,
    "league_id": 8,
    "season_id": 19735,
    "starting_at_timestamp": 1_800_000_000,
    "participants": [
        {"id": 1, "meta": {"location": "home"}},
        {"id": 3, "meta": {"location": "away"}},
    ],
    "scores": [],
    "state": {"short_name": "NS"},
}


# --- fixture status mapping --------------------------------------------------


def test_map_fixture_status_passthrough_for_known_code():
    assert mappers.map_fixture_status({"state": {"short_name": "FT"}}) == "FT"


def test_map_fixture_status_translates_sportmonks_code():
    assert mappers.map_fixture_status({"state": {"short_name": "inplay_1st_half"}}) == "LIVE"


def test_map_fixture_status_defaults_to_ns_for_unknown_code(caplog):
    assert mappers.map_fixture_status({"state": {"short_name": "SOMETHING_NEW"}}) == "NS"


def test_map_fixture_status_defaults_to_ns_when_missing():
    assert mappers.map_fixture_status({}) == "NS"


# --- kickoff parsing ----------------------------------------------------------


def test_parse_kickoff_prefers_timestamp():
    dt = mappers.parse_kickoff({"starting_at_timestamp": 1_800_000_000, "starting_at": "1999-01-01 00:00:00"})
    assert dt == datetime.fromtimestamp(1_800_000_000, tz=timezone.utc)


def test_parse_kickoff_falls_back_to_string():
    dt = mappers.parse_kickoff({"starting_at": "2024-08-17 15:00:00"})
    assert dt == datetime(2024, 8, 17, 15, 0, tzinfo=timezone.utc)


def test_parse_kickoff_missing_raises():
    with pytest.raises(MappingError):
        mappers.parse_kickoff({})


def test_parse_kickoff_unparseable_raises():
    with pytest.raises(MappingError):
        mappers.parse_kickoff({"starting_at": "not-a-date"})


# --- map_fixture ---------------------------------------------------------------


def test_map_fixture_finished_match():
    result = mappers.map_fixture(FINISHED_FIXTURE)
    assert result == {
        "id": 18528480,
        "league_id": 8,
        "season_id": 19735,
        "kickoff": datetime(2024, 8, 17, 15, 0, tzinfo=timezone.utc),
        "home_team_id": 1,
        "away_team_id": 2,
        "home_goals": 2,
        "away_goals": 1,
        "status": "FT",
    }


def test_map_fixture_upcoming_match_has_no_goals():
    result = mappers.map_fixture(UPCOMING_FIXTURE)
    assert result["home_goals"] is None
    assert result["away_goals"] is None
    assert result["status"] == "NS"
    assert result["home_team_id"] == 1
    assert result["away_team_id"] == 3


def test_map_fixture_missing_participants_raises():
    broken = {**FINISHED_FIXTURE, "participants": [{"id": 1, "meta": {"location": "home"}}]}
    with pytest.raises(MappingError):
        mappers.map_fixture(broken)


def test_map_fixture_missing_required_ids_raises():
    with pytest.raises(MappingError):
        mappers.map_fixture({"participants": FINISHED_FIXTURE["participants"]})


# --- map_league / map_team / map_season ----------------------------------------


def test_map_league():
    result = mappers.map_league(FINISHED_FIXTURE["league"])
    assert result == {
        "id": 8,
        "name": "Premier League",
        "country_id": 462,
        "country_name": None,
        "is_active": True,
    }


def test_map_league_missing_id_raises():
    with pytest.raises(MappingError):
        mappers.map_league({"name": "No ID League"})


def test_map_team_minimal():
    result = mappers.map_team({"id": 1, "name": "Home FC"})
    assert result["id"] == 1
    assert result["name"] == "Home FC"
    assert result["short_code"] is None
    assert result["founded"] is None


def test_map_season():
    result = mappers.map_season(FINISHED_FIXTURE["season"])
    assert result == {
        "id": 19735,
        "league_id": 8,
        "name": "2024/2025",
        "start_date": datetime(2024, 8, 10).date(),
        "end_date": datetime(2025, 5, 25).date(),
        "is_current": True,
    }


# --- statistics / xg ------------------------------------------------------------


def test_map_match_statistics_extracts_configured_stats():
    rows = mappers.map_match_statistics(
        FINISHED_FIXTURE, {"shots_total": 42, "corners": None, "fouls": None}
    )
    by_team = {row["team_id"]: row for row in rows}
    assert by_team[1]["shots_total"] == 15
    assert by_team[2]["shots_total"] == 9
    assert "corners" not in by_team[1]  # unconfigured (None) type_id never matches


def test_map_match_statistics_with_no_configured_ids_returns_empty():
    assert mappers.map_match_statistics(FINISHED_FIXTURE, {"shots_total": None}) == []


def test_map_match_xg():
    rows = mappers.map_match_xg(FINISHED_FIXTURE, xg_type_id=86)
    by_team = {row["team_id"]: row["xg"] for row in rows}
    assert by_team == {1: 1.8, 2: 0.9}
    assert all(row["source"] == "sportmonks" for row in rows)


def test_map_match_xg_unconfigured_returns_empty():
    assert mappers.map_match_xg(FINISHED_FIXTURE, xg_type_id=None) == []


# --- sportmonks predictions ------------------------------------------------------


def test_map_sportmonks_prediction_extracts_over_2_5():
    retrieved_at = datetime(2024, 8, 17, 10, 0, tzinfo=timezone.utc)
    result = mappers.map_sportmonks_prediction(
        FINISHED_FIXTURE, over_2_5_type_id=231, retrieved_at=retrieved_at
    )
    assert result["fixture_id"] == 18528480
    assert result["over_2_5_probability"] == pytest.approx(0.625)
    assert result["btts_probability"] is None
    assert result["retrieved_at"] == retrieved_at


def test_map_sportmonks_prediction_unconfigured_returns_none():
    assert (
        mappers.map_sportmonks_prediction(
            FINISHED_FIXTURE,
            over_2_5_type_id=None,
            retrieved_at=datetime.now(timezone.utc),
        )
        is None
    )


def test_map_sportmonks_prediction_no_matching_market_returns_none():
    result = mappers.map_sportmonks_prediction(
        FINISHED_FIXTURE, over_2_5_type_id=99999, retrieved_at=datetime.now(timezone.utc)
    )
    assert result is None


# --- odds ---------------------------------------------------------------------


def test_map_odds_pairs_over_under_per_bookmaker():
    retrieved_at = datetime(2024, 8, 17, 10, 0, tzinfo=timezone.utc)
    rows = mappers.map_odds(FINISHED_FIXTURE, market_id=12, retrieved_at=retrieved_at)
    by_bookmaker = {row["bookmaker"]: row for row in rows}

    assert set(by_bookmaker) == {"2", "5"}  # bookmaker 9 dropped: wrong line, no pair
    assert by_bookmaker["2"]["over_odds"] == 1.85
    assert by_bookmaker["2"]["under_odds"] == 2.10
    assert by_bookmaker["5"]["over_odds"] == 1.90


def test_map_odds_uses_bookmaker_name_lookup():
    rows = mappers.map_odds(
        FINISHED_FIXTURE,
        market_id=12,
        retrieved_at=datetime.now(timezone.utc),
        bookmaker_names={2: "Average"},
    )
    names = {row["bookmaker"] for row in rows}
    assert "Average" in names
    assert "5" in names  # no name configured -> falls back to the raw id


def test_map_odds_unconfigured_returns_empty():
    assert mappers.map_odds(FINISHED_FIXTURE, market_id=None, retrieved_at=datetime.now(timezone.utc)) == []


def test_map_odds_drops_incomplete_pairs():
    fixture = {
        "id": 1,
        "odds": [{"market_id": 12, "bookmaker_id": 1, "label": "Over", "total": "2.5", "value": "1.80"}],
    }
    assert mappers.map_odds(fixture, market_id=12, retrieved_at=datetime.now(timezone.utc)) == []
