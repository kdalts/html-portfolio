"""Tests for the daily report generator and sender."""

from datetime import date, datetime, timezone

import httpx

from app.automation.report import generate_daily_report, send_report
from app.db.models.evaluation import DailyRanking
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.predictions import ModelPrediction

UTC = timezone.utc
NOW = datetime.now(UTC)
RANKING_DATE = date(2024, 8, 17)


def _seed_ranked_fixture(session):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    session.add(Team(id=1, name="Arsenal"))
    session.add(Team(id=2, name="Chelsea"))
    session.flush()
    session.add(
        Fixture(
            id=1, league_id=1, season_id=1, kickoff=datetime(2024, 8, 17, 15, 0, tzinfo=UTC),
            home_team_id=1, away_team_id=2, status="NS",
        )
    )
    session.flush()
    prediction = ModelPrediction(
        fixture_id=1, model_version="v1", predicted_at=NOW, final_probability=0.68, market_probability=0.58,
    )
    session.add(prediction)
    session.flush()
    session.add(
        DailyRanking(
            ranking_date=RANKING_DATE, fixture_id=1, model_prediction_id=prediction.id, rank=1,
            ranking_score=0.5, final_probability=0.68, confidence_score=0.62, market_probability=0.58,
            edge=prediction.edge, generated_at=NOW,
        )
    )
    session.flush()


def test_report_for_date_with_no_ranking(db_session):
    text = generate_daily_report(db_session, RANKING_DATE)
    assert "No qualifying selections" in text
    assert str(RANKING_DATE) in text


def test_report_includes_teams_and_figures(db_session):
    _seed_ranked_fixture(db_session)
    text = generate_daily_report(db_session, RANKING_DATE)
    assert "Arsenal vs Chelsea" in text
    assert "Premier League" in text
    assert "68.0%" in text  # probability
    assert "62.0%" in text  # confidence
    assert "+10.0%" in text  # edge = 0.68 - 0.58


def test_report_never_claims_certainty(db_session):
    _seed_ranked_fixture(db_session)
    text = generate_daily_report(db_session, RANKING_DATE)
    assert "guarantee" in text.lower()


def _set_base_env(monkeypatch):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")


def test_send_report_logs_when_no_webhook_configured(monkeypatch):
    from app.core.config import get_settings

    _set_base_env(monkeypatch)
    get_settings.cache_clear()
    monkeypatch.delenv("DAILY_REPORT_WEBHOOK_URL", raising=False)
    delivered = send_report("test report body")
    assert delivered is False
    get_settings.cache_clear()


def test_send_report_posts_to_configured_webhook(monkeypatch):
    from app.core.config import get_settings

    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))

        class _Resp:
            def raise_for_status(self):
                pass

        return _Resp()

    _set_base_env(monkeypatch)
    monkeypatch.setattr("app.automation.report.httpx.post", fake_post)
    monkeypatch.setenv("DAILY_REPORT_WEBHOOK_URL", "https://example.test/webhook")
    get_settings.cache_clear()

    delivered = send_report("hello")
    assert delivered is True
    assert calls == [("https://example.test/webhook", {"text": "hello"})]
    get_settings.cache_clear()


def test_send_report_falls_back_to_logging_on_delivery_failure(monkeypatch):
    from app.core.config import get_settings

    def failing_post(url, json, timeout):
        raise httpx.ConnectError("connection refused")

    _set_base_env(monkeypatch)
    monkeypatch.setattr("app.automation.report.httpx.post", failing_post)
    monkeypatch.setenv("DAILY_REPORT_WEBHOOK_URL", "https://example.test/webhook")
    get_settings.cache_clear()

    delivered = send_report("hello")
    assert delivered is False
    get_settings.cache_clear()
