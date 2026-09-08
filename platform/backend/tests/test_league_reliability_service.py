"""Integration tests for league reliability aggregation and storage,
against a real PostgreSQL database."""

from datetime import date, datetime, timezone

from sqlalchemy import select

from app.db.models.evaluation import BacktestResult, LeagueModelPerformance
from app.db.models.leagues_teams import League
from app.ranking.league_reliability_service import compute_and_store_league_reliability

UTC = timezone.utc
NOW = datetime.now(UTC)


def _add_backtest_row(session, *, run_id, league_id, model_type, sample_size, brier_score, calibration_error):
    session.add(
        BacktestResult(
            backtest_run_id=run_id,
            train_start_date=date(2019, 1, 1),
            train_end_date=date(2023, 1, 1),
            test_start_date=date(2023, 1, 1),
            test_end_date=date(2024, 1, 1),
            model_type=model_type,
            segment_type="league",
            segment_value=str(league_id),
            sample_size=sample_size,
            brier_score=brier_score,
            calibration_error=calibration_error,
        )
    )
    session.flush()


def test_aggregates_across_multiple_runs_and_stores(db_session):
    session = db_session
    session.add(League(id=1, name="Premier League"))
    session.flush()

    _add_backtest_row(session, run_id="wf-x-2023", league_id=1, model_type="poisson", sample_size=100, brier_score=0.05, calibration_error=0.01)
    _add_backtest_row(session, run_id="wf-x-2024", league_id=1, model_type="poisson", sample_size=150, brier_score=0.04, calibration_error=0.01)

    summary = compute_and_store_league_reliability(
        session,
        backtest_run_ids=["wf-x-2023", "wf-x-2024"],
        model_type="poisson",
        evaluation_window_start=date(2019, 1, 1),
        evaluation_window_end=date(2024, 1, 1),
        commit=False,
    )
    session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1

    row = session.execute(
        select(LeagueModelPerformance).where(LeagueModelPerformance.league_id == 1, LeagueModelPerformance.model_type == "poisson")
    ).scalar_one()
    assert row.sample_size == 250  # 100 + 150
    # sample-size-weighted average: (0.05*100 + 0.04*150) / 250
    assert row.brier_score == (0.05 * 100 + 0.04 * 150) / 250
    assert row.is_eligible is True  # decent sample, good metrics


def test_low_sample_league_is_not_eligible(db_session):
    session = db_session
    session.add(League(id=1, name="Small League"))
    session.flush()
    _add_backtest_row(session, run_id="wf-y-2023", league_id=1, model_type="poisson", sample_size=5, brier_score=0.20, calibration_error=0.05)

    compute_and_store_league_reliability(
        session, backtest_run_ids=["wf-y-2023"], model_type="poisson",
        evaluation_window_start=date(2019, 1, 1), evaluation_window_end=date(2024, 1, 1), commit=False,
    )
    session.flush()

    row = session.execute(select(LeagueModelPerformance).where(LeagueModelPerformance.league_id == 1)).scalar_one()
    assert row.is_eligible is False


def test_rerun_with_different_window_updates_in_place(db_session):
    session = db_session
    session.add(League(id=1, name="Premier League"))
    session.flush()
    _add_backtest_row(session, run_id="wf-z-2023", league_id=1, model_type="poisson", sample_size=100, brier_score=0.30, calibration_error=0.10)

    compute_and_store_league_reliability(
        session, backtest_run_ids=["wf-z-2023"], model_type="poisson",
        evaluation_window_start=date(2019, 1, 1), evaluation_window_end=date(2024, 1, 1), commit=False,
    )
    session.flush()
    compute_and_store_league_reliability(
        session, backtest_run_ids=["wf-z-2023"], model_type="poisson",
        evaluation_window_start=date(2019, 1, 1), evaluation_window_end=date(2024, 1, 1), commit=False,
    )
    session.flush()

    rows = session.execute(select(LeagueModelPerformance).where(LeagueModelPerformance.league_id == 1)).scalars().all()
    assert len(rows) == 1  # same (league_id, model_type, evaluation_window_end) -> updated in place, not duplicated


def test_leagues_with_no_matching_backtest_rows_are_skipped(db_session):
    session = db_session
    session.add(League(id=1, name="Premier League"))
    session.flush()
    summary = compute_and_store_league_reliability(
        session, backtest_run_ids=["nonexistent-run"], model_type="poisson",
        evaluation_window_start=date(2019, 1, 1), evaluation_window_end=date(2024, 1, 1), commit=False,
    )
    assert summary.fetched == 0
    assert summary.upserted == 0
