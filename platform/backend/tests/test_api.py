"""Integration tests for the read API, against a real PostgreSQL database
via FastAPI's TestClient. Reuses the app's normal DB dependency
(app.db.session.get_db) overridden to return the test's db_session, so
these exercise the actual route/schema wiring, not a mock."""

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.models.evaluation import BacktestResult, DailyRanking, LeagueModelPerformance
from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.predictions import ModelPrediction
from app.db.session import get_db

UTC = timezone.utc
NOW = datetime.now(UTC)
RANKING_DATE = date(2024, 8, 17)
KICKOFF = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)


@pytest.fixture
def client(db_session, monkeypatch):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_full_fixture(session):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()

    fixture = Fixture(
        id=1, league_id=1, season_id=1, kickoff=KICKOFF, home_team_id=1, away_team_id=2, status="NS",
    )
    session.add(fixture)
    session.flush()

    session.add(TeamFeatures(team_id=1, fixture_id=1, is_home=True, as_of=KICKOFF, computed_at=NOW, overall_last5_goals_scored=2.0))
    session.add(TeamFeatures(team_id=2, fixture_id=1, is_home=False, as_of=KICKOFF, computed_at=NOW, overall_last5_goals_scored=1.0))
    session.add(MatchFeatures(fixture_id=1, league_avg_goals=2.6, data_completeness_score=0.8, computed_at=NOW))
    session.flush()

    prediction = ModelPrediction(
        fixture_id=1, model_version="v1", predicted_at=NOW,
        poisson_probability=0.6, ml_probability=0.62, final_probability=0.63,
        market_probability=0.55, ensemble_weights={"poisson_probability": 0.5, "ml_probability": 0.5},
        calibration_method="isotonic",
    )
    session.add(prediction)
    session.flush()

    session.add(
        LeagueModelPerformance(
            league_id=1, model_type="final", evaluation_window_start=date(2019, 1, 1), evaluation_window_end=date(2024, 1, 1),
            sample_size=300, brier_score=0.18, league_reliability_score=0.8, is_eligible=True, computed_at=NOW,
        )
    )
    session.add(
        DailyRanking(
            ranking_date=RANKING_DATE, fixture_id=1, model_prediction_id=prediction.id, rank=1,
            ranking_score=0.5, final_probability=0.63, confidence_score=0.7, market_probability=0.55,
            edge=prediction.edge, generated_at=NOW,
        )
    )
    session.flush()
    return fixture, prediction


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_daily_ranking_endpoint(client, db_session):
    _seed_full_fixture(db_session)
    response = client.get("/api/rankings/daily", params={"ranking_date": "2024-08-17"})
    assert response.status_code == 200
    body = response.json()
    assert body["ranking_date"] == "2024-08-17"
    assert len(body["rankings"]) == 1
    entry = body["rankings"][0]
    assert entry["rank"] == 1
    assert entry["home_team"] == "Home FC"
    assert entry["away_team"] == "Away FC"
    assert entry["league_name"] == "Premier League"
    assert entry["final_probability"] == 0.63
    assert entry["poisson_probability"] == 0.6


def test_daily_ranking_empty_date_returns_empty_list(client, db_session):
    response = client.get("/api/rankings/daily", params={"ranking_date": "2030-01-01"})
    assert response.status_code == 200
    assert response.json()["rankings"] == []


def test_fixture_detail_endpoint(client, db_session):
    _seed_full_fixture(db_session)
    response = client.get("/api/fixtures/1")
    assert response.status_code == 200
    body = response.json()
    assert body["home_team"] == "Home FC"
    assert body["away_team"] == "Away FC"
    assert body["home_form"]["overall_last5_goals_scored"] == 2.0
    assert body["match_features"]["league_avg_goals"] == 2.6
    assert body["prediction"]["final_probability"] == 0.63
    assert "isotonic" in body["prediction"]["explanation"]
    assert body["confidence_score"] == 0.7  # pulled from the daily_rankings row


def test_fixture_detail_404_for_unknown_fixture(client, db_session):
    response = client.get("/api/fixtures/999999")
    assert response.status_code == 404


def test_league_performance_endpoint(client, db_session):
    _seed_full_fixture(db_session)
    response = client.get("/api/leagues/performance")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["league_name"] == "Premier League"
    assert body[0]["is_eligible"] is True


def test_model_performance_endpoint(client, db_session):
    db_session.add(League(id=1, name="Premier League"))
    db_session.flush()
    db_session.add(
        BacktestResult(
            backtest_run_id="wf-x-2024", train_start_date=date(2019, 1, 1), train_end_date=date(2024, 1, 1),
            test_start_date=date(2024, 1, 1), test_end_date=date(2025, 1, 1), model_type="poisson",
            segment_type="overall", segment_value="ALL", sample_size=500, brier_score=0.2, log_loss=0.6,
        )
    )
    db_session.flush()

    response = client.get("/api/models/performance")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["model_type"] == "poisson"
    assert body[0]["sample_size"] == 500


def test_backtest_runs_endpoint(client, db_session):
    db_session.add(League(id=1, name="Premier League"))
    db_session.flush()
    db_session.add(
        BacktestResult(
            backtest_run_id="wf-x-2024", train_start_date=date(2019, 1, 1), train_end_date=date(2024, 1, 1),
            test_start_date=date(2024, 1, 1), test_end_date=date(2025, 1, 1), model_type="poisson",
            segment_type="overall", segment_value="ALL", sample_size=500, brier_score=0.2,
        )
    )
    db_session.add(
        BacktestResult(
            backtest_run_id="wf-x-2024", train_start_date=date(2019, 1, 1), train_end_date=date(2024, 1, 1),
            test_start_date=date(2024, 1, 1), test_end_date=date(2025, 1, 1), model_type="poisson",
            segment_type="probability_band", segment_value="60-65", sample_size=50,
            predicted_probability_mean=0.62, actual_frequency=0.6,
        )
    )
    db_session.flush()

    response = client.get("/api/backtest/runs")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["backtest_run_id"] == "wf-x-2024"
    assert len(body[0]["probability_bands"]) == 1
    assert body[0]["probability_bands"][0]["band"] == "60-65"


def test_system_health_endpoint(client, db_session):
    _seed_full_fixture(db_session)
    response = client.get("/api/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database_connected"] is True
    assert body["counts"]["fixtures"] == 1
    assert body["counts"]["leagues"] == 1
