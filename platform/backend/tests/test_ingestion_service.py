"""Integration tests for the ingestion orchestration service: a mocked
SportmonksClient (httpx.MockTransport, as in Phase 1) feeding a real
PostgreSQL database, proving batch ingestion is idempotent and that one
malformed record never aborts the rest of the batch.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import MatchStatistics, MatchXG
from app.integrations.sportmonks.client import SportmonksClient
from app.ingestion import repository, service
from app.ingestion.errors import LeakageError

UTC = timezone.utc


def _client(dummy_settings, handler) -> SportmonksClient:
    return SportmonksClient(settings=dummy_settings, transport=httpx.MockTransport(handler))


def _fixture(id_, *, home_id=1, away_id=2, home_goals=2, away_goals=1, status="FT"):
    return {
        "id": id_,
        "league_id": 8,
        "season_id": 19735,
        "starting_at": "2024-08-17 15:00:00",
        "participants": [
            {"id": home_id, "name": f"Team {home_id}", "meta": {"location": "home"}},
            {"id": away_id, "name": f"Team {away_id}", "meta": {"location": "away"}},
        ],
        "scores": [
            {"description": "CURRENT", "participant_id": home_id, "score": {"goals": home_goals}},
            {"description": "CURRENT", "participant_id": away_id, "score": {"goals": away_goals}},
        ],
        "state": {"short_name": status},
        "league": {"id": 8, "name": "Premier League", "active": True},
        "season": {"id": 19735, "league_id": 8, "name": "2024/2025", "is_current": True},
        "statistics": [
            {"type_id": 42, "participant_id": home_id, "data": {"value": 15}},
            {"type_id": 42, "participant_id": away_id, "data": {"value": 9}},
            {"type_id": 86, "participant_id": home_id, "data": {"value": 1.8}},
            {"type_id": 86, "participant_id": away_id, "data": {"value": 0.9}},
        ],
    }


def _paginated_response(items: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"data": items, "pagination": {"has_more": False}})


def test_ingest_leagues_upserts_and_is_idempotent(dummy_settings, db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        return _paginated_response([{"id": 8, "name": "Premier League", "active": True}])

    client = _client(dummy_settings, handler)
    summary = service.ingest_leagues(client, db_session, commit=False)
    db_session.flush()
    summary2 = service.ingest_leagues(client, db_session, commit=False)
    db_session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1
    assert summary.failed == 0
    assert bool(summary) is True
    assert summary2.upserted == 1  # re-running is safe

    rows = db_session.execute(select(League)).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "Premier League"


def test_ingest_fixtures_between_creates_league_season_teams_and_fixture(dummy_settings, db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        return _paginated_response([_fixture(1)])

    client = _client(dummy_settings, handler)
    summary = service.ingest_fixtures_between(client, db_session, "2024-08-01", "2024-08-31", commit=False)
    db_session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1
    assert summary.failed == 0

    assert db_session.get(League, 8) is not None
    assert db_session.get(Season, 19735) is not None
    assert db_session.get(Team, 1) is not None
    assert db_session.get(Team, 2) is not None
    fixture = db_session.get(Fixture, 1)
    assert fixture is not None
    assert fixture.home_goals == 2
    assert fixture.away_goals == 1
    assert fixture.total_goals == 3
    assert fixture.over_2_5 is True


def test_ingest_fixtures_between_is_idempotent(dummy_settings, db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        return _paginated_response([_fixture(1)])

    client = _client(dummy_settings, handler)
    service.ingest_fixtures_between(client, db_session, "2024-08-01", "2024-08-31", commit=False)
    db_session.flush()
    service.ingest_fixtures_between(client, db_session, "2024-08-01", "2024-08-31", commit=False)
    db_session.flush()

    rows = db_session.execute(select(Fixture)).scalars().all()
    assert len(rows) == 1  # no duplicate created by the second run


def test_ingest_fixtures_between_with_statistics_populates_match_data(dummy_settings, db_session):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "statistics" in request.url.params.get("include", "")
        return _paginated_response([_fixture(1)])

    client = _client(dummy_settings, handler)
    summary = service.ingest_fixtures_between(
        client,
        db_session,
        "2024-08-01",
        "2024-08-31",
        ingest_statistics=True,
        statistic_type_ids={"shots_total": 42},
        xg_type_id=86,
        commit=False,
    )
    db_session.flush()

    assert summary.failed == 0
    stats = db_session.execute(select(MatchStatistics)).scalars().all()
    xg_rows = db_session.execute(select(MatchXG)).scalars().all()
    assert {s.team_id: s.shots_total for s in stats} == {1: 15, 2: 9}
    assert {x.team_id: x.xg for x in xg_rows} == {1: 1.8, 2: 0.9}


def test_one_malformed_fixture_does_not_abort_the_batch(dummy_settings, db_session):
    """A fixture missing its home/away participants must be skipped and
    recorded as a failure, while every other fixture in the same batch
    still gets ingested — one bad record must never poison the whole run."""
    broken = _fixture(2)
    broken["participants"] = [broken["participants"][0]]  # drop the away team

    def handler(request: httpx.Request) -> httpx.Response:
        return _paginated_response([_fixture(1), broken, _fixture(3, home_id=1, away_id=4)])

    client = _client(dummy_settings, handler)
    summary = service.ingest_fixtures_between(client, db_session, "2024-08-01", "2024-08-31", commit=False)
    db_session.flush()

    assert summary.fetched == 3
    assert summary.upserted == 2
    assert summary.failed == 1
    assert bool(summary) is False
    assert any("2" in err for err in summary.errors)

    assert db_session.get(Fixture, 1) is not None
    assert db_session.get(Fixture, 2) is None  # the broken one never got written
    assert db_session.get(Fixture, 3) is not None


def test_ingest_prediction_for_fixture_respects_leakage_guard(dummy_settings, db_session):
    repository.upsert_league(db_session, {"id": 8, "name": "Premier League"})
    repository.upsert_team(db_session, {"id": 1, "name": "A"})
    repository.upsert_team(db_session, {"id": 2, "name": "B"})
    repository.upsert_season(db_session, {"id": 19735, "league_id": 8, "name": "2024/2025"})
    kickoff = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)
    repository.upsert_fixture(
        db_session,
        {
            "id": 1,
            "league_id": 8,
            "season_id": 19735,
            "kickoff": kickoff,
            "home_team_id": 1,
            "away_team_id": 2,
            "status": "NS",
        },
    )
    db_session.flush()
    fixture = db_session.get(Fixture, 1)

    raw_fixture = {"id": 1, "predictions": [{"type_id": 231, "predictions": {"yes": 60.0, "no": 40.0}}]}

    # a plausible pre-kickoff retrieval succeeds
    stored = service.ingest_prediction_for_fixture(
        db_session,
        fixture,
        raw_fixture,
        over_2_5_type_id=231,
        retrieved_at=kickoff - timedelta(hours=1),
        commit=False,
    )
    assert stored is True

    # simulate a historical-backfill-style call that would retrieve "now"
    # (long after kickoff) - must be refused
    with pytest.raises(LeakageError):
        service.ingest_prediction_for_fixture(
            db_session,
            fixture,
            raw_fixture,
            over_2_5_type_id=231,
            retrieved_at=kickoff + timedelta(days=10),
            commit=False,
        )
