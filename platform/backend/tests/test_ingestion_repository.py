"""Integration tests for the idempotent upsert repository, against a real
PostgreSQL database (see conftest.py db_session fixture)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import MatchStatistics, Odds, SportmonksPrediction
from app.ingestion import repository
from app.ingestion.errors import LeakageError

UTC = timezone.utc


def _seed_league_teams_season(session):
    session.add_all(
        [
            League(id=1, name="Premier League"),
            Team(id=1, name="Home FC"),
            Team(id=2, name="Away FC"),
            Season(id=1, league_id=1, name="2024/2025"),
        ]
    )
    session.flush()


def test_upsert_league_is_idempotent(db_session):
    repository.upsert_league(db_session, {"id": 1, "name": "Premier League", "is_active": True})
    repository.upsert_league(db_session, {"id": 1, "name": "Premier League (renamed)", "is_active": True})
    db_session.flush()

    rows = db_session.execute(select(League).where(League.id == 1)).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "Premier League (renamed)"


def test_upsert_fixture_is_idempotent_and_updates_goals(db_session):
    _seed_league_teams_season(db_session)
    fixture_values = {
        "id": 1,
        "league_id": 1,
        "season_id": 1,
        "kickoff": datetime(2024, 8, 17, 15, 0, tzinfo=UTC),
        "home_team_id": 1,
        "away_team_id": 2,
        "home_goals": None,
        "away_goals": None,
        "status": "NS",
    }
    repository.upsert_fixture(db_session, fixture_values)
    db_session.flush()

    updated_values = {**fixture_values, "home_goals": 2, "away_goals": 1, "status": "FT"}
    repository.upsert_fixture(db_session, updated_values)
    db_session.flush()

    rows = db_session.execute(select(Fixture).where(Fixture.id == 1)).scalars().all()
    assert len(rows) == 1
    assert rows[0].home_goals == 2
    assert rows[0].away_goals == 1
    assert rows[0].total_goals == 3  # generated column recomputed through the upsert
    assert rows[0].over_2_5 is True
    assert rows[0].status == "FT"


def test_upsert_match_statistics_conflict_key_is_fixture_and_team(db_session):
    _seed_league_teams_season(db_session)
    repository.upsert_fixture(
        db_session,
        {
            "id": 1,
            "league_id": 1,
            "season_id": 1,
            "kickoff": datetime(2024, 8, 17, 15, 0, tzinfo=UTC),
            "home_team_id": 1,
            "away_team_id": 2,
            "status": "FT",
        },
    )
    db_session.flush()

    repository.upsert_match_statistics(db_session, {"fixture_id": 1, "team_id": 1, "shots_total": 10})
    repository.upsert_match_statistics(db_session, {"fixture_id": 1, "team_id": 1, "shots_total": 15})
    db_session.flush()

    rows = db_session.execute(
        select(MatchStatistics).where(MatchStatistics.fixture_id == 1, MatchStatistics.team_id == 1)
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].shots_total == 15


@pytest.fixture
def finished_fixture(db_session):
    _seed_league_teams_season(db_session)
    kickoff = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)
    repository.upsert_fixture(
        db_session,
        {
            "id": 1,
            "league_id": 1,
            "season_id": 1,
            "kickoff": kickoff,
            "home_team_id": 1,
            "away_team_id": 2,
            "home_goals": 2,
            "away_goals": 1,
            "status": "FT",
        },
    )
    db_session.flush()
    return db_session.get(Fixture, 1)


def test_upsert_sportmonks_prediction_before_kickoff_succeeds(db_session, finished_fixture):
    retrieved_at = finished_fixture.kickoff - timedelta(hours=1)
    repository.upsert_sportmonks_prediction(
        db_session,
        {
            "fixture_id": 1,
            "over_2_5_probability": 0.6,
            "btts_probability": None,
            "predicted_home_goals": None,
            "predicted_away_goals": None,
            "raw_payload": None,
            "retrieved_at": retrieved_at,
        },
        kickoff=finished_fixture.kickoff,
    )
    db_session.flush()
    row = db_session.execute(select(SportmonksPrediction).where(SportmonksPrediction.fixture_id == 1)).scalar_one()
    assert row.over_2_5_probability == 0.6


def test_upsert_sportmonks_prediction_after_kickoff_is_refused(db_session, finished_fixture):
    """The realistic historical-backfill trap: pulling a 'prediction' for
    a fixture long after it kicked off must never be stored."""
    retrieved_at = finished_fixture.kickoff + timedelta(days=30)
    with pytest.raises(LeakageError):
        repository.upsert_sportmonks_prediction(
            db_session,
            {
                "fixture_id": 1,
                "over_2_5_probability": 0.6,
                "btts_probability": None,
                "predicted_home_goals": None,
                "predicted_away_goals": None,
                "raw_payload": None,
                "retrieved_at": retrieved_at,
            },
            kickoff=finished_fixture.kickoff,
        )
    # and nothing was written
    rows = db_session.execute(select(SportmonksPrediction).where(SportmonksPrediction.fixture_id == 1)).scalars().all()
    assert rows == []


def test_upsert_odds_after_kickoff_is_refused(db_session, finished_fixture):
    retrieved_at = finished_fixture.kickoff + timedelta(days=1)
    with pytest.raises(LeakageError):
        repository.upsert_odds(
            db_session,
            {
                "fixture_id": 1,
                "bookmaker": "average",
                "market": "over_under_2_5",
                "over_odds": 1.85,
                "under_odds": 2.10,
                "retrieved_at": retrieved_at,
            },
            kickoff=finished_fixture.kickoff,
        )
    rows = db_session.execute(select(Odds).where(Odds.fixture_id == 1)).scalars().all()
    assert rows == []


def test_upsert_odds_before_kickoff_succeeds(db_session, finished_fixture):
    retrieved_at = finished_fixture.kickoff - timedelta(hours=2)
    repository.upsert_odds(
        db_session,
        {
            "fixture_id": 1,
            "bookmaker": "average",
            "market": "over_under_2_5",
            "over_odds": 1.85,
            "under_odds": 2.10,
            "retrieved_at": retrieved_at,
        },
        kickoff=finished_fixture.kickoff,
    )
    db_session.flush()
    row = db_session.execute(select(Odds).where(Odds.fixture_id == 1)).scalar_one()
    assert row.over_odds == 1.85
    assert row.market_probability is not None  # generated column computed
