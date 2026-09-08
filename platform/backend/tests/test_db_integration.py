"""Integration tests against a real PostgreSQL database (see conftest.py
db_engine/db_session fixtures — TEST_DATABASE_URL, or these tests skip).

These prove the schema behaves correctly where it matters most: the
Over 2.5 target label is computed by the database itself, market/edge
derived columns can't drift from their inputs, and referential integrity
(cascade vs restrict) matches the intended data-lifecycle rules.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.models import Base
from app.db.models.evaluation import DailyRanking
from app.db.models.features import TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import MatchStatistics, Odds
from app.db.models.predictions import ModelPrediction

UTC = timezone.utc


def _seed_minimal(session):
    """League, two teams, a season, and a not-started fixture, ready to
    have goals/stats/predictions attached in individual tests."""
    league = League(id=1, name="Premier League", is_active=True)
    home = Team(id=1, name="Home FC")
    away = Team(id=2, name="Away FC")
    season = Season(id=1, league_id=1, name="2024/2025", is_current=True)
    session.add_all([league, home, away, season])
    session.flush()

    fixture = Fixture(
        id=1,
        league_id=1,
        season_id=1,
        kickoff=datetime(2024, 8, 1, 15, 0, tzinfo=UTC),
        home_team_id=1,
        away_team_id=2,
        status="NS",
    )
    session.add(fixture)
    session.flush()
    return fixture


# --- schema-level sanity ----------------------------------------------------


def test_migration_created_every_table(db_engine):
    inspector = inspect(db_engine)
    existing = set(inspector.get_table_names())
    expected = set(Base.metadata.tables.keys())
    assert expected <= existing


# --- target label correctness (generated columns) --------------------------


@pytest.mark.parametrize(
    "home_goals,away_goals,expected_total,expected_over",
    [
        (2, 1, 3, True),  # exactly 3 -> over
        (1, 1, 2, False),  # under
        (0, 0, 0, False),
        (3, 2, 5, True),
        (None, None, None, None),  # not yet played
    ],
)
def test_over_2_5_label_is_computed_correctly(
    db_session, home_goals, away_goals, expected_total, expected_over
):
    fixture = _seed_minimal(db_session)
    fixture.home_goals = home_goals
    fixture.away_goals = away_goals
    fixture.status = "FT" if home_goals is not None else "NS"
    db_session.flush()
    db_session.refresh(fixture)

    assert fixture.total_goals == expected_total
    assert fixture.over_2_5 == expected_over


def test_one_goal_missing_yields_null_target(db_session):
    """A partially-updated score must never resolve to a false 0/1 label."""
    fixture = _seed_minimal(db_session)
    fixture.home_goals = 2
    fixture.away_goals = None
    db_session.flush()
    db_session.refresh(fixture)

    assert fixture.total_goals is None
    assert fixture.over_2_5 is None


# --- constraints -------------------------------------------------------------


def test_fixture_rejects_invalid_status(db_session):
    fixture = _seed_minimal(db_session)
    fixture.status = "BOGUS"
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_fixture_rejects_same_team_home_and_away(db_session):
    league = League(id=1, name="Premier League")
    team = Team(id=1, name="Solo FC")
    season = Season(id=1, league_id=1, name="2024/2025")
    db_session.add_all([league, team, season])
    db_session.flush()

    fixture = Fixture(
        id=1,
        league_id=1,
        season_id=1,
        kickoff=datetime(2024, 8, 1, tzinfo=UTC),
        home_team_id=1,
        away_team_id=1,
        status="NS",
    )
    db_session.add(fixture)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_fixture_rejects_negative_goals(db_session):
    fixture = _seed_minimal(db_session)
    fixture.home_goals = -1
    fixture.away_goals = 0
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_fixture_requires_existing_league(db_session):
    team_a = Team(id=1, name="A")
    team_b = Team(id=2, name="B")
    db_session.add_all([team_a, team_b])
    db_session.flush()

    fixture = Fixture(
        id=1,
        league_id=999,  # does not exist
        season_id=999,
        kickoff=datetime(2024, 8, 1, tzinfo=UTC),
        home_team_id=1,
        away_team_id=2,
        status="NS",
    )
    db_session.add(fixture)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_team_features_unique_per_team_and_fixture(db_session):
    fixture = _seed_minimal(db_session)
    now = datetime.now(UTC)
    first = TeamFeatures(
        team_id=1, fixture_id=fixture.id, is_home=True, as_of=fixture.kickoff, computed_at=now
    )
    duplicate = TeamFeatures(
        team_id=1, fixture_id=fixture.id, is_home=True, as_of=fixture.kickoff, computed_at=now
    )
    db_session.add(first)
    db_session.flush()
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_daily_rankings_rejects_duplicate_rank_on_same_day(db_session):
    fixture = _seed_minimal(db_session)
    prediction = ModelPrediction(
        fixture_id=fixture.id,
        model_version="v1",
        final_probability=0.6,
        confidence_score=0.5,
        predicted_at=datetime(2024, 7, 31, tzinfo=UTC),
    )
    db_session.add(prediction)
    db_session.flush()

    ranking_date = date(2024, 8, 1)
    first = DailyRanking(
        ranking_date=ranking_date,
        fixture_id=fixture.id,
        model_prediction_id=prediction.id,
        rank=1,
        ranking_score=0.9,
        final_probability=0.6,
        confidence_score=0.5,
        generated_at=datetime.now(UTC),
    )
    db_session.add(first)
    db_session.flush()

    # A second fixture ranked #1 on the same day should be rejected.
    league = db_session.get(League, 1)
    away2 = Team(id=3, name="Third FC")
    db_session.add(away2)
    db_session.flush()
    fixture2 = Fixture(
        id=2,
        league_id=league.id,
        season_id=1,
        kickoff=datetime(2024, 8, 1, tzinfo=UTC),
        home_team_id=1,
        away_team_id=3,
        status="NS",
    )
    db_session.add(fixture2)
    db_session.flush()
    prediction2 = ModelPrediction(
        fixture_id=fixture2.id,
        model_version="v1",
        final_probability=0.7,
        confidence_score=0.6,
        predicted_at=datetime(2024, 7, 31, tzinfo=UTC),
    )
    db_session.add(prediction2)
    db_session.flush()

    duplicate_rank = DailyRanking(
        ranking_date=ranking_date,
        fixture_id=fixture2.id,
        model_prediction_id=prediction2.id,
        rank=1,
        ranking_score=0.95,
        final_probability=0.7,
        confidence_score=0.6,
        generated_at=datetime.now(UTC),
    )
    db_session.add(duplicate_rank)
    with pytest.raises(IntegrityError):
        db_session.flush()


# --- derived/generated columns for odds and edge ----------------------------


def test_odds_market_probability_is_devigged_correctly(db_session):
    fixture = _seed_minimal(db_session)
    odds = Odds(
        fixture_id=fixture.id,
        bookmaker="average",
        market="over_under_2_5",
        over_odds=1.80,
        under_odds=2.20,
        retrieved_at=datetime.now(UTC),
    )
    db_session.add(odds)
    db_session.flush()
    db_session.refresh(odds)

    over_implied = 1 / 1.80
    under_implied = 1 / 2.20
    expected_market_prob = over_implied / (over_implied + under_implied)

    assert odds.over_implied_probability == pytest.approx(over_implied, rel=1e-6)
    assert odds.under_implied_probability == pytest.approx(under_implied, rel=1e-6)
    assert odds.overround == pytest.approx(over_implied + under_implied, rel=1e-6)
    assert odds.market_probability == pytest.approx(expected_market_prob, rel=1e-6)
    # a real market always overrounds above 100% (the bookmaker's margin)
    assert odds.overround > 1.0


def test_model_prediction_edge_is_final_minus_market(db_session):
    fixture = _seed_minimal(db_session)
    prediction = ModelPrediction(
        fixture_id=fixture.id,
        model_version="v1",
        final_probability=0.62,
        market_probability=0.55,
        confidence_score=0.5,
        predicted_at=datetime.now(UTC),
    )
    db_session.add(prediction)
    db_session.flush()
    db_session.refresh(prediction)

    assert prediction.edge == pytest.approx(0.07, rel=1e-6)


def test_model_prediction_edge_is_null_without_market_probability(db_session):
    fixture = _seed_minimal(db_session)
    prediction = ModelPrediction(
        fixture_id=fixture.id,
        model_version="v1",
        final_probability=0.62,
        confidence_score=0.5,
        predicted_at=datetime.now(UTC),
    )
    db_session.add(prediction)
    db_session.flush()
    db_session.refresh(prediction)

    assert prediction.edge is None


# --- cascade vs restrict delete behavior ------------------------------------


def test_deleting_fixture_cascades_to_dependent_rows(db_session):
    fixture = _seed_minimal(db_session)
    stats = MatchStatistics(fixture_id=fixture.id, team_id=1, shots_total=10)
    db_session.add(stats)
    db_session.flush()

    db_session.delete(fixture)
    db_session.flush()

    remaining = db_session.execute(
        select(MatchStatistics).where(MatchStatistics.fixture_id == 1)
    ).scalars().all()
    assert remaining == []


def test_deleting_team_referenced_by_fixture_is_restricted(db_session):
    fixture = _seed_minimal(db_session)
    home_team = db_session.get(Team, fixture.home_team_id)
    db_session.delete(home_team)
    with pytest.raises(IntegrityError):
        db_session.flush()
