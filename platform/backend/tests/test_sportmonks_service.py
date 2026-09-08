"""Integration tests for syncing Sportmonks predictions into
model_predictions, against a real PostgreSQL database."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import SportmonksPrediction
from app.db.models.predictions import ModelPrediction
from app.models.sportmonks_service import sync_and_store_sportmonks_predictions, sync_sportmonks_prediction_for_fixture

UTC = timezone.utc
NOW = datetime.now(UTC)


def _seed_fixture(session, fixture_id=1, *, kickoff=None):
    kickoff = kickoff or datetime(2024, 8, 17, 15, 0, tzinfo=UTC)
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()
    fixture = Fixture(
        id=fixture_id, league_id=1, season_id=1, kickoff=kickoff, home_team_id=1, away_team_id=2, status="NS",
    )
    session.add(fixture)
    session.flush()
    return fixture


def test_sync_copies_probability_from_sportmonks_predictions(db_session):
    fixture = _seed_fixture(db_session)
    db_session.add(
        SportmonksPrediction(
            fixture_id=fixture.id, over_2_5_probability=0.63, retrieved_at=fixture.kickoff - timedelta(hours=2)
        )
    )
    db_session.flush()

    values = sync_sportmonks_prediction_for_fixture(db_session, fixture)
    assert values["sportmonks_probability"] == 0.63
    assert values["fixture_id"] == fixture.id


def test_sync_returns_none_without_an_ingested_prediction(db_session):
    fixture = _seed_fixture(db_session)
    assert sync_sportmonks_prediction_for_fixture(db_session, fixture) is None


def test_sync_returns_none_when_probability_field_itself_is_null(db_session):
    fixture = _seed_fixture(db_session)
    db_session.add(
        SportmonksPrediction(
            fixture_id=fixture.id, over_2_5_probability=None, btts_probability=0.4,
            retrieved_at=fixture.kickoff - timedelta(hours=1),
        )
    )
    db_session.flush()
    assert sync_sportmonks_prediction_for_fixture(db_session, fixture) is None


def test_sync_preserves_existing_predicted_at(db_session):
    fixture = _seed_fixture(db_session)
    db_session.add(
        SportmonksPrediction(
            fixture_id=fixture.id, over_2_5_probability=0.63, retrieved_at=fixture.kickoff - timedelta(hours=2)
        )
    )
    original_predicted_at = datetime(2024, 8, 1, tzinfo=UTC)
    db_session.add(ModelPrediction(fixture_id=fixture.id, model_version="v1", poisson_probability=0.55, predicted_at=original_predicted_at))
    db_session.flush()

    values = sync_sportmonks_prediction_for_fixture(db_session, fixture)
    assert values["predicted_at"] == original_predicted_at


def test_batch_merges_into_existing_row_without_clobbering(db_session):
    fixture = _seed_fixture(db_session)
    db_session.add(
        SportmonksPrediction(
            fixture_id=fixture.id, over_2_5_probability=0.63, retrieved_at=fixture.kickoff - timedelta(hours=2)
        )
    )
    db_session.add(ModelPrediction(fixture_id=fixture.id, model_version="v1", poisson_probability=0.55, predicted_at=NOW))
    db_session.flush()

    summary = sync_and_store_sportmonks_predictions(db_session, [fixture], commit=False)
    db_session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1
    assert summary.failed == 0

    row = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == fixture.id)).scalar_one()
    assert row.poisson_probability == 0.55  # untouched
    assert row.sportmonks_probability == 0.63


def test_batch_records_failure_for_fixture_without_ingested_prediction(db_session):
    fixture = _seed_fixture(db_session)
    summary = sync_and_store_sportmonks_predictions(db_session, [fixture], commit=False)
    assert summary.fetched == 1
    assert summary.upserted == 0
    assert summary.failed == 1


def test_batch_is_idempotent(db_session):
    fixture = _seed_fixture(db_session)
    db_session.add(
        SportmonksPrediction(
            fixture_id=fixture.id, over_2_5_probability=0.71, retrieved_at=fixture.kickoff - timedelta(hours=1)
        )
    )
    db_session.flush()

    sync_and_store_sportmonks_predictions(db_session, [fixture], commit=False)
    db_session.flush()
    sync_and_store_sportmonks_predictions(db_session, [fixture], commit=False)
    db_session.flush()

    rows = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == fixture.id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].sportmonks_probability == 0.71
