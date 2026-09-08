"""Integration tests for the Poisson model service, against a real
PostgreSQL database. Seeds team_features/match_features rows directly
(bypassing Phase 4's own computation) so these tests stay focused on
Phase 5's own logic: reading features, computing an estimate, and storing
it on model_predictions."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.predictions import ModelPrediction
from app.models.poisson_service import compute_and_store_poisson_predictions, compute_poisson_prediction_for_fixture

UTC = timezone.utc
NOW = datetime.now(UTC)


def _seed_fixture(session, fixture_id=1, *, status="NS"):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()

    fixture = Fixture(
        id=fixture_id,
        league_id=1,
        season_id=1,
        kickoff=datetime(2024, 8, 17, 15, 0, tzinfo=UTC),
        home_team_id=1,
        away_team_id=2,
        status=status,
    )
    session.add(fixture)
    session.flush()
    return fixture


def _seed_features(session, fixture):
    session.add(
        TeamFeatures(
            team_id=fixture.home_team_id,
            fixture_id=fixture.id,
            is_home=True,
            as_of=fixture.kickoff,
            computed_at=NOW,
            venue_last10_goals_scored=2.0,
            venue_last10_goals_conceded=1.0,
            venue_last10_matches_played=10,
        )
    )
    session.add(
        TeamFeatures(
            team_id=fixture.away_team_id,
            fixture_id=fixture.id,
            is_home=False,
            as_of=fixture.kickoff,
            computed_at=NOW,
            venue_last10_goals_scored=1.0,
            venue_last10_goals_conceded=1.8,
            venue_last10_matches_played=10,
        )
    )
    session.add(
        MatchFeatures(
            fixture_id=fixture.id,
            league_home_goals_avg=1.5,
            league_away_goals_avg=1.2,
            computed_at=NOW,
        )
    )
    session.flush()


def test_compute_poisson_prediction_for_fixture_returns_expected_values(db_session):
    fixture = _seed_fixture(db_session)
    _seed_features(db_session, fixture)

    values = compute_poisson_prediction_for_fixture(db_session, fixture)

    assert values["fixture_id"] == fixture.id
    assert values["expected_home_goals"] == 2.4
    assert 0.8 < values["expected_away_goals"] < 0.9
    assert 0.0 <= values["poisson_probability"] <= 1.0
    assert values["predicted_at"] is not None


def test_compute_poisson_prediction_returns_none_without_features(db_session):
    fixture = _seed_fixture(db_session)
    # no team_features/match_features seeded
    assert compute_poisson_prediction_for_fixture(db_session, fixture) is None


def test_batch_stores_prediction_row(db_session):
    fixture = _seed_fixture(db_session)
    _seed_features(db_session, fixture)

    summary = compute_and_store_poisson_predictions(db_session, [fixture], commit=False)
    db_session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1
    assert summary.failed == 0

    row = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == fixture.id)).scalar_one()
    assert row.model_version == "v1"
    assert row.expected_home_goals == 2.4
    assert row.poisson_probability is not None
    # columns from other phases stay untouched (None), not fabricated
    assert row.ml_probability is None
    assert row.sportmonks_probability is None


def test_batch_is_idempotent_and_does_not_clobber_other_columns(db_session):
    fixture = _seed_fixture(db_session)
    _seed_features(db_session, fixture)

    # simulate a later phase having already written ml_probability on the
    # same (fixture_id, model_version) row
    db_session.add(
        ModelPrediction(
            fixture_id=fixture.id,
            model_version="v1",
            ml_probability=0.71,
            predicted_at=NOW,
        )
    )
    db_session.flush()

    compute_and_store_poisson_predictions(db_session, [fixture], commit=False)
    db_session.flush()

    rows = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == fixture.id)).scalars().all()
    assert len(rows) == 1  # merged into the same row, not duplicated
    assert rows[0].ml_probability == 0.71  # untouched by the Poisson upsert
    assert rows[0].poisson_probability is not None  # and now also populated


def test_batch_records_failure_for_fixture_missing_features(db_session):
    with_features = _seed_fixture(db_session, fixture_id=1)
    _seed_features(db_session, with_features)

    session2 = db_session
    session2.add(Team(id=3, name="Third FC"))
    session2.flush()
    without_features = Fixture(
        id=2,
        league_id=1,
        season_id=1,
        kickoff=datetime(2024, 8, 18, tzinfo=UTC),
        home_team_id=1,
        away_team_id=3,
        status="NS",
    )
    session2.add(without_features)
    session2.flush()

    summary = compute_and_store_poisson_predictions(db_session, [with_features, without_features], commit=False)
    db_session.flush()

    assert summary.fetched == 2
    assert summary.upserted == 1
    assert summary.failed == 1
    assert any("2" in err for err in summary.errors)

    assert db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == 1)).scalar_one_or_none()
    assert db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == 2)).scalar_one_or_none() is None
