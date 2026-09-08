"""Integration tests for syncing market odds into model_predictions,
against a real PostgreSQL database."""

import inspect
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import Odds
from app.db.models.predictions import ModelPrediction
from app.models import odds_service
from app.models.odds_service import build_market_snapshot, sync_and_store_market_data, sync_market_data_for_fixture

UTC = timezone.utc
NOW = datetime.now(UTC)
KICKOFF = datetime(2024, 8, 17, 15, 0, tzinfo=UTC)


def _seed_fixture(session, fixture_id=1):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()
    fixture = Fixture(id=fixture_id, league_id=1, season_id=1, kickoff=KICKOFF, home_team_id=1, away_team_id=2, status="NS")
    session.add(fixture)
    session.flush()
    return fixture


def _add_odds(session, fixture_id, bookmaker, over_odds, under_odds, retrieved_at):
    session.add(
        Odds(
            fixture_id=fixture_id, bookmaker=bookmaker, market="over_under_2_5",
            over_odds=over_odds, under_odds=under_odds, retrieved_at=retrieved_at,
        )
    )
    session.flush()


# --- source-level guarantee: never reads the raw (vig-inflated) implied probability


def test_module_never_accesses_raw_implied_probability():
    """The docstring mentions the raw fields by name to explain why they
    aren't used - this checks the CODE never actually reads them (as an
    attribute access, e.g. `row.over_implied_probability`)."""
    source = inspect.getsource(odds_service)
    assert ".over_implied_probability" not in source
    assert ".under_implied_probability" not in source


# --- build_market_snapshot ---------------------------------------------------------


def test_snapshot_uses_devigged_market_probability_not_raw_odds(db_session):
    fixture = _seed_fixture(db_session)
    _add_odds(db_session, fixture.id, "average", 1.80, 2.20, KICKOFF - timedelta(hours=1))
    db_session.flush()

    row = db_session.execute(select(Odds).where(Odds.fixture_id == fixture.id)).scalar_one()
    snapshot = build_market_snapshot(db_session, fixture.id)

    assert snapshot.market_probability == pytest.approx(row.market_probability)
    over_implied_raw = 1 / 1.80
    assert snapshot.market_probability != pytest.approx(over_implied_raw)  # de-vigged, not raw
    assert snapshot.odds_id == row.id  # single bookmaker -> traceable


def test_snapshot_averages_across_multiple_bookmakers(db_session):
    fixture = _seed_fixture(db_session)
    _add_odds(db_session, fixture.id, "bookmaker_a", 1.80, 2.20, KICKOFF - timedelta(hours=2))
    _add_odds(db_session, fixture.id, "bookmaker_b", 1.90, 2.00, KICKOFF - timedelta(hours=1))
    db_session.flush()

    snapshot = build_market_snapshot(db_session, fixture.id)
    assert snapshot.bookmaker_count == 2
    assert snapshot.odds_id is None  # ambiguous across multiple bookmakers -> not traceable to one row
    assert snapshot.market_odds_over == pytest.approx((1.80 + 1.90) / 2)


def test_snapshot_uses_latest_per_bookmaker_not_every_snapshot(db_session):
    fixture = _seed_fixture(db_session)
    _add_odds(db_session, fixture.id, "average", 1.70, 2.30, KICKOFF - timedelta(hours=5))  # stale
    _add_odds(db_session, fixture.id, "average", 1.85, 2.10, KICKOFF - timedelta(hours=1))  # latest
    db_session.flush()

    snapshot = build_market_snapshot(db_session, fixture.id)
    assert snapshot.bookmaker_count == 1
    assert snapshot.market_odds_over == pytest.approx(1.85)


def test_snapshot_none_without_any_odds(db_session):
    fixture = _seed_fixture(db_session)
    assert build_market_snapshot(db_session, fixture.id) is None


def test_implausible_overround_is_rejected(db_session):
    fixture = _seed_fixture(db_session)
    # absurdly generous odds -> overround well under 1.0, implausible
    _add_odds(db_session, fixture.id, "average", 10.0, 10.0, KICKOFF - timedelta(hours=1))
    db_session.flush()
    assert build_market_snapshot(db_session, fixture.id) is None


# --- sync + edge integration --------------------------------------------------------


def test_sync_merges_into_existing_row_and_edge_generated_column_follows(db_session):
    fixture = _seed_fixture(db_session)
    _add_odds(db_session, fixture.id, "average", 1.80, 2.20, KICKOFF - timedelta(hours=1))
    db_session.add(ModelPrediction(fixture_id=fixture.id, model_version="v1", final_probability=0.62, predicted_at=NOW))
    db_session.flush()

    summary = sync_and_store_market_data(db_session, [fixture], commit=False)
    db_session.flush()

    assert summary.upserted == 1
    row = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == fixture.id)).scalar_one()
    assert row.final_probability == 0.62  # untouched
    assert row.market_probability is not None
    assert row.edge == pytest.approx(row.final_probability - row.market_probability)  # DB-generated, not Python-computed


def test_sync_preserves_existing_predicted_at(db_session):
    fixture = _seed_fixture(db_session)
    _add_odds(db_session, fixture.id, "average", 1.80, 2.20, KICKOFF - timedelta(hours=1))
    original_predicted_at = datetime(2024, 8, 1, tzinfo=UTC)
    db_session.add(ModelPrediction(fixture_id=fixture.id, model_version="v1", poisson_probability=0.5, predicted_at=original_predicted_at))
    db_session.flush()

    values = sync_market_data_for_fixture(db_session, fixture)
    assert values["predicted_at"] == original_predicted_at


def test_batch_records_failure_without_odds(db_session):
    fixture = _seed_fixture(db_session)
    summary = sync_and_store_market_data(db_session, [fixture], commit=False)
    assert summary.fetched == 1
    assert summary.upserted == 0
    assert summary.failed == 1


def test_batch_is_idempotent(db_session):
    fixture = _seed_fixture(db_session)
    _add_odds(db_session, fixture.id, "average", 1.80, 2.20, KICKOFF - timedelta(hours=1))
    db_session.flush()

    sync_and_store_market_data(db_session, [fixture], commit=False)
    db_session.flush()
    sync_and_store_market_data(db_session, [fixture], commit=False)
    db_session.flush()

    rows = db_session.execute(select(ModelPrediction).where(ModelPrediction.fixture_id == fixture.id)).scalars().all()
    assert len(rows) == 1
