"""Integration tests for walk-forward backtesting: real PostgreSQL + real
(small) XGBoost training runs per fold, with model artifacts written to a
pytest tmp_path."""

import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.backtest.walkforward import WalkForwardFold, run_walkforward_backtest
from app.db.models.evaluation import BacktestResult
from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team

UTC = timezone.utc
NOW = datetime.now(UTC)
BASE_DATE = datetime(2020, 1, 1, tzinfo=UTC)


def _seed_base(session):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2020"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()


def _seed_fixture(session, fixture_id, kickoff, *, signal, label):
    home_goals, away_goals = (2, 1) if label == 1 else (1, 0)
    session.add(
        Fixture(
            id=fixture_id,
            league_id=1,
            season_id=1,
            kickoff=kickoff,
            home_team_id=1,
            away_team_id=2,
            home_goals=home_goals,
            away_goals=away_goals,
            status="FT",
        )
    )
    session.flush()
    session.add(
        TeamFeatures(
            team_id=1,
            fixture_id=fixture_id,
            is_home=True,
            as_of=kickoff,
            computed_at=NOW,
            overall_last10_goals_scored=signal,
            venue_last10_goals_scored=signal,
            venue_last10_goals_conceded=1.0 - signal * 0.5,
        )
    )
    session.add(
        TeamFeatures(
            team_id=2,
            fixture_id=fixture_id,
            is_home=False,
            as_of=kickoff,
            computed_at=NOW,
            overall_last10_goals_scored=1.0 - signal,
            venue_last10_goals_scored=1.0 - signal,
            venue_last10_goals_conceded=signal * 0.5 + 0.5,
        )
    )
    session.add(MatchFeatures(fixture_id=fixture_id, league_avg_goals=2.5, league_home_goals_avg=1.5, league_away_goals_avg=1.2, computed_at=NOW))
    session.flush()


def _seed_dataset(session, *, n_train, n_test, train_start, test_start, seed):
    rng = random.Random(seed)
    fixture_id = 1
    for i in range(n_train):
        signal = rng.uniform(0, 1)
        label = 1 if signal > 0.5 else 0
        _seed_fixture(session, fixture_id, train_start + timedelta(days=i), signal=signal, label=label)
        fixture_id += 1
    for i in range(n_test):
        signal = rng.uniform(0, 1)
        label = 1 if signal > 0.5 else 0
        _seed_fixture(session, fixture_id, test_start + timedelta(days=i), signal=signal, label=label)
        fixture_id += 1


def test_walkforward_writes_backtest_results_for_each_model_type(db_session, tmp_path):
    _seed_base(db_session)
    train_start = BASE_DATE
    train_end = BASE_DATE + timedelta(days=100)
    test_end = train_end + timedelta(days=30)
    _seed_dataset(db_session, n_train=100, n_test=20, train_start=train_start, test_start=train_end, seed=1)

    fold = WalkForwardFold(train_start=train_start, train_end=train_end, test_end=test_end, label="fold1")
    run_ids = run_walkforward_backtest(
        db_session, folds=[fold], run_tag="test", artifact_dir=tmp_path, commit=False
    )
    db_session.flush()

    assert run_ids == ["wf-test-fold1"]
    rows = db_session.execute(select(BacktestResult).where(BacktestResult.backtest_run_id == "wf-test-fold1")).scalars().all()
    model_types_present = {r.model_type for r in rows}
    assert model_types_present == {"poisson", "ml"}

    overall_poisson = next(r for r in rows if r.model_type == "poisson" and r.segment_type == "overall")
    assert overall_poisson.sample_size == 20
    assert overall_poisson.train_start_date == train_start.date()
    assert overall_poisson.train_end_date == train_end.date()
    assert overall_poisson.test_start_date == train_end.date()
    assert overall_poisson.test_end_date == test_end.date()

    overall_ml = next(r for r in rows if r.model_type == "ml" and r.segment_type == "overall")
    assert overall_ml.sample_size == 20


def _seed_fixture_with_realistic_goal_rates(session, fixture_id, kickoff, *, rng):
    # Realistic goal-rate ranges (~0.5-3.0), independent per team, so the
    # resulting Poisson lambda spans both sides of the Over 2.5 threshold
    # - unlike _seed_fixture's tiny 0-1 ranges (max lambda ~0.67, always
    # under 3), which this test needs to actually exercise the bands.
    home_scored = rng.uniform(0.5, 3.0)
    home_conceded = rng.uniform(0.5, 2.5)
    away_scored = rng.uniform(0.5, 3.0)
    away_conceded = rng.uniform(0.5, 2.5)
    label = 1 if (home_scored + away_scored) >= 3 else 0
    home_goals, away_goals = (2, 1) if label == 1 else (1, 0)

    session.add(Fixture(
        id=fixture_id, league_id=1, season_id=1, kickoff=kickoff,
        home_team_id=1, away_team_id=2, home_goals=home_goals, away_goals=away_goals, status="FT",
    ))
    session.flush()
    session.add(TeamFeatures(
        team_id=1, fixture_id=fixture_id, is_home=True, as_of=kickoff, computed_at=NOW,
        venue_last10_goals_scored=home_scored, venue_last10_goals_conceded=home_conceded,
    ))
    session.add(TeamFeatures(
        team_id=2, fixture_id=fixture_id, is_home=False, as_of=kickoff, computed_at=NOW,
        venue_last10_goals_scored=away_scored, venue_last10_goals_conceded=away_conceded,
    ))
    session.add(MatchFeatures(
        fixture_id=fixture_id, league_avg_goals=2.5, league_home_goals_avg=1.5, league_away_goals_avg=1.2, computed_at=NOW,
    ))
    session.flush()


def test_walkforward_produces_probability_band_and_home_away_segments(db_session, tmp_path):
    _seed_base(db_session)
    train_start = BASE_DATE
    train_end = BASE_DATE + timedelta(days=100)
    test_end = train_end + timedelta(days=30)
    rng = random.Random(2)
    for i in range(20):
        _seed_fixture_with_realistic_goal_rates(db_session, i + 1, train_end + timedelta(days=i), rng=rng)

    fold = WalkForwardFold(train_start=train_start, train_end=train_end, test_end=test_end, label="fold1")
    run_walkforward_backtest(db_session, folds=[fold], model_types=("poisson",), run_tag="test", artifact_dir=tmp_path, commit=False)
    db_session.flush()

    rows = db_session.execute(select(BacktestResult).where(BacktestResult.backtest_run_id == "wf-test-fold1")).scalars().all()
    segment_types = {r.segment_type for r in rows}
    assert "probability_band" in segment_types
    assert "home_away" in segment_types
    assert "league" in segment_types
    assert "season" in segment_types


def test_walkforward_ml_model_never_trains_on_data_at_or_after_train_end(db_session, tmp_path):
    """The central leakage guarantee of this phase: the ML artifact for a
    fold must be trained using only [train_start, train_end) data - proven
    directly from the artifact's own metadata sidecar."""
    _seed_base(db_session)
    train_start = BASE_DATE
    train_end = BASE_DATE + timedelta(days=100)
    test_end = train_end + timedelta(days=30)
    _seed_dataset(db_session, n_train=100, n_test=20, train_start=train_start, test_start=train_end, seed=3)

    fold = WalkForwardFold(train_start=train_start, train_end=train_end, test_end=test_end, label="fold1")
    run_walkforward_backtest(db_session, folds=[fold], model_types=("ml",), run_tag="test", artifact_dir=tmp_path, commit=False)
    db_session.flush()

    metadata = json.loads((tmp_path / "backtest-fold1.meta.json").read_text())
    stored_train_end = datetime.fromisoformat(metadata["train_end"])
    stored_val_end = datetime.fromisoformat(metadata["val_end"])
    assert stored_train_end < train_end  # internal train/val split stays strictly inside the fold's training window
    assert stored_val_end == train_end  # the validation tail never reaches into the fold's test window


def test_walkforward_is_idempotent_on_rerun(db_session, tmp_path):
    _seed_base(db_session)
    train_start = BASE_DATE
    train_end = BASE_DATE + timedelta(days=100)
    test_end = train_end + timedelta(days=30)
    _seed_dataset(db_session, n_train=100, n_test=20, train_start=train_start, test_start=train_end, seed=4)

    fold = WalkForwardFold(train_start=train_start, train_end=train_end, test_end=test_end, label="fold1")
    run_walkforward_backtest(db_session, folds=[fold], model_types=("poisson",), run_tag="rerun", artifact_dir=tmp_path, commit=False)
    db_session.flush()
    run_walkforward_backtest(db_session, folds=[fold], model_types=("poisson",), run_tag="rerun", artifact_dir=tmp_path, commit=False)
    db_session.flush()

    rows = db_session.execute(select(BacktestResult).where(BacktestResult.backtest_run_id == "wf-rerun-fold1")).scalars().all()
    keys = [(r.model_type, r.segment_type, r.segment_value) for r in rows]
    assert len(keys) == len(set(keys))  # no duplicates despite running twice


def test_walkforward_skips_fold_with_no_test_fixtures(db_session, tmp_path):
    _seed_base(db_session)
    fold = WalkForwardFold(
        train_start=BASE_DATE, train_end=BASE_DATE + timedelta(days=10), test_end=BASE_DATE + timedelta(days=20), label="empty"
    )
    run_ids = run_walkforward_backtest(db_session, folds=[fold], run_tag="empty-test", artifact_dir=tmp_path, commit=False)
    db_session.flush()
    assert run_ids == ["wf-empty-test-empty"]
    rows = db_session.execute(select(BacktestResult).where(BacktestResult.backtest_run_id == "wf-empty-test-empty")).scalars().all()
    assert rows == []  # nothing to evaluate, nothing written - not an error
