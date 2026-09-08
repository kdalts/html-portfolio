"""Integration tests for the daily ranking engine, against a real
PostgreSQL database."""

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db.models.evaluation import DailyRanking, LeagueModelPerformance
from app.db.models.features import MatchFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.predictions import ModelPrediction
from app.ranking.daily_ranking_service import build_daily_ranking

UTC = timezone.utc
NOW = datetime.now(UTC)
RANKING_DATE = date(2024, 8, 17)


def _kickoff(hour: int) -> datetime:
    return datetime(2024, 8, 17, hour, 0, tzinfo=UTC)


def _seed_league(session, league_id, *, reliability_score, is_eligible, model_type="final"):
    session.add(League(id=league_id, name=f"League {league_id}"))
    session.add(Season(id=league_id, league_id=league_id, name="2024/2025"))
    session.flush()
    session.add(
        LeagueModelPerformance(
            league_id=league_id, model_type=model_type,
            evaluation_window_start=date(2019, 1, 1), evaluation_window_end=date(2024, 1, 1),
            sample_size=300, league_reliability_score=reliability_score, is_eligible=is_eligible, computed_at=NOW,
        )
    )
    session.flush()


def _seed_fixture(
    session, fixture_id, *, league_id, hour, final_probability, completeness=0.9,
    probs=(0.7, 0.72, 0.71), edge=None, market_probability=None, status="NS",
):
    home_id, away_id = fixture_id * 10 + 1, fixture_id * 10 + 2
    session.add(Team(id=home_id, name=f"Home {fixture_id}"))
    session.add(Team(id=away_id, name=f"Away {fixture_id}"))
    session.flush()
    fixture = Fixture(
        id=fixture_id, league_id=league_id, season_id=league_id, kickoff=_kickoff(hour),
        home_team_id=home_id, away_team_id=away_id, status=status,
    )
    session.add(fixture)
    session.flush()
    session.add(MatchFeatures(fixture_id=fixture_id, data_completeness_score=completeness, computed_at=NOW))
    session.add(
        ModelPrediction(
            fixture_id=fixture_id, model_version="v1", predicted_at=NOW,
            poisson_probability=probs[0], ml_probability=probs[1], sportmonks_probability=probs[2],
            final_probability=final_probability, market_probability=market_probability,
        )
    )
    session.flush()
    return fixture


def test_qualifying_fixtures_are_ranked_highest_score_first(db_session):
    _seed_league(db_session, 1, reliability_score=0.9, is_eligible=True)
    _seed_fixture(db_session, 1, league_id=1, hour=12, final_probability=0.55)
    _seed_fixture(db_session, 2, league_id=1, hour=15, final_probability=0.85)
    _seed_fixture(db_session, 3, league_id=1, hour=18, final_probability=0.70)

    result = build_daily_ranking(db_session, ranking_date=RANKING_DATE, reliability_model_type="final", commit=False)
    db_session.flush()

    assert result["considered"] == 3
    assert result["qualified"] == 3
    assert result["ranked"] == 3

    rows = (
        db_session.execute(select(DailyRanking).where(DailyRanking.ranking_date == RANKING_DATE).order_by(DailyRanking.rank))
        .scalars()
        .all()
    )
    assert [r.fixture_id for r in rows] == [2, 3, 1]  # highest probability -> best rank, given equal confidence
    assert [r.rank for r in rows] == [1, 2, 3]


def test_ineligible_league_is_excluded(db_session):
    _seed_league(db_session, 1, reliability_score=0.1, is_eligible=False)
    _seed_fixture(db_session, 1, league_id=1, hour=12, final_probability=0.9)

    result = build_daily_ranking(db_session, ranking_date=RANKING_DATE, reliability_model_type="final", commit=False)
    assert result["qualified"] == 0
    assert "league not eligible" in result["excluded"][1]


def test_fixture_without_prediction_is_excluded(db_session):
    _seed_league(db_session, 1, reliability_score=0.9, is_eligible=True)
    session = db_session
    session.add(Team(id=101, name="Home"))
    session.add(Team(id=102, name="Away"))
    session.flush()
    fixture = Fixture(id=1, league_id=1, season_id=1, kickoff=_kickoff(12), home_team_id=101, away_team_id=102, status="NS")
    session.add(fixture)
    session.flush()

    result = build_daily_ranking(session, ranking_date=RANKING_DATE, reliability_model_type="final", commit=False)
    assert result["qualified"] == 0
    assert "no final_probability" in result["excluded"][1]


def test_low_confidence_fixture_is_excluded(db_session):
    _seed_league(db_session, 1, reliability_score=0.9, is_eligible=True)
    # low data completeness -> low confidence regardless of high probability
    _seed_fixture(db_session, 1, league_id=1, hour=12, final_probability=0.9, completeness=0.02)

    result = build_daily_ranking(db_session, ranking_date=RANKING_DATE, reliability_model_type="final", commit=False)
    assert result["qualified"] == 0
    assert "confidence" in result["excluded"][1]


def test_top_n_is_respected(db_session):
    _seed_league(db_session, 1, reliability_score=0.9, is_eligible=True)
    for i in range(1, 6):
        _seed_fixture(db_session, i, league_id=1, hour=10 + i, final_probability=0.5 + i * 0.05)

    result = build_daily_ranking(db_session, ranking_date=RANKING_DATE, reliability_model_type="final", top_n=3, commit=False)
    db_session.flush()
    assert result["qualified"] == 5
    assert result["ranked"] == 3

    rows = db_session.execute(select(DailyRanking).where(DailyRanking.ranking_date == RANKING_DATE)).scalars().all()
    assert len(rows) == 3


def test_rerun_clears_previous_ranking_for_the_same_date(db_session):
    _seed_league(db_session, 1, reliability_score=0.9, is_eligible=True)
    _seed_fixture(db_session, 1, league_id=1, hour=12, final_probability=0.9)
    build_daily_ranking(db_session, ranking_date=RANKING_DATE, reliability_model_type="final", commit=False)
    db_session.flush()

    _seed_fixture(db_session, 2, league_id=1, hour=15, final_probability=0.95)
    build_daily_ranking(db_session, ranking_date=RANKING_DATE, reliability_model_type="final", commit=False)
    db_session.flush()

    rows = db_session.execute(select(DailyRanking).where(DailyRanking.ranking_date == RANKING_DATE)).scalars().all()
    assert len(rows) == 2  # both fixtures present, no leftover duplicate from the first run


def test_only_not_started_fixtures_on_the_target_date_are_considered(db_session):
    _seed_league(db_session, 1, reliability_score=0.9, is_eligible=True)
    _seed_fixture(db_session, 1, league_id=1, hour=12, final_probability=0.9, status="FT")  # already played
    _seed_fixture(db_session, 2, league_id=1, hour=12, final_probability=0.9)
    # different day entirely
    other_day_fixture_id = 3
    session = db_session
    session.add(Team(id=301, name="Home"))
    session.add(Team(id=302, name="Away"))
    session.flush()
    session.add(Fixture(id=other_day_fixture_id, league_id=1, season_id=1, kickoff=datetime(2024, 8, 18, 12, tzinfo=UTC), home_team_id=301, away_team_id=302, status="NS"))
    session.flush()

    result = build_daily_ranking(db_session, ranking_date=RANKING_DATE, reliability_model_type="final", commit=False)
    assert result["considered"] == 1  # only fixture 2: NS and on 2024-08-17
