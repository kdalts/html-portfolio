"""Integration tests for the daily automation pipeline: real PostgreSQL,
mocked Sportmonks HTTP (as in Phase 1/3), proving the full run executes
every step, isolates failures correctly, and (given the necessary
prerequisites) produces an actual ranked selection end to end."""

import random
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.automation.daily_pipeline import run_daily_pipeline
from app.db.models.evaluation import DailyRanking, LeagueModelPerformance
from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.predictions import ModelPrediction
from app.integrations.sportmonks.client import SportmonksClient
from app.models.ensemble_service import fit_ensemble_and_calibration
from app.models.ml_service import train_and_save_model

UTC = timezone.utc
NOW = datetime.now(UTC)
RANKING_DATE = date(2024, 8, 20)
KICKOFF = datetime(2024, 8, 20, 15, 0, tzinfo=UTC)


def _fixture_payload(fixture_id, home_id, away_id, kickoff, *, include_predictions=False, include_odds=False):
    payload = {
        "id": fixture_id,
        "league_id": 8,
        "season_id": 19735,
        "starting_at": kickoff.strftime("%Y-%m-%d %H:%M:%S"),
        "participants": [
            {"id": home_id, "name": f"Team {home_id}", "meta": {"location": "home"}},
            {"id": away_id, "name": f"Team {away_id}", "meta": {"location": "away"}},
        ],
        "scores": [],
        "state": {"short_name": "NS"},
        "league": {"id": 8, "name": "Premier League", "active": True},
        "season": {"id": 19735, "league_id": 8, "name": "2024/2025", "is_current": True},
    }
    if include_predictions:
        payload["predictions"] = [{"type_id": 231, "predictions": {"yes": 60.0, "no": 40.0}}]
    if include_odds:
        payload["odds"] = [
            {"market_id": 12, "bookmaker_id": 1, "label": "Over", "total": "2.5", "value": "1.85"},
            {"market_id": 12, "bookmaker_id": 1, "label": "Under", "total": "2.5", "value": "2.05"},
        ]
    return payload


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if "/fixtures/between/" in path:
        return httpx.Response(
            200,
            json={"data": [_fixture_payload(1, 1, 2, KICKOFF)], "pagination": {"has_more": False}},
        )
    if path.endswith("/fixtures/1"):
        include = request.url.params.get("include", "")
        return httpx.Response(
            200,
            json={
                "data": _fixture_payload(
                    1, 1, 2, KICKOFF, include_predictions="predictions" in include, include_odds="odds" in include
                )
            },
        )
    return httpx.Response(404, json={"message": "not found"})


def _client(dummy_settings) -> SportmonksClient:
    return SportmonksClient(settings=dummy_settings, transport=httpx.MockTransport(_handler))


def test_pipeline_runs_every_step_and_isolates_missing_prerequisites(db_session, dummy_settings, tmp_path):
    client = _client(dummy_settings)
    report = run_daily_pipeline(
        db_session,
        client,
        ranking_date=RANKING_DATE,
        settings=dummy_settings,
        ml_artifact_dir=tmp_path / "ml",
        ensemble_artifact_dir=tmp_path / "ensemble",
        commit=False,
    )

    step_names = [s.name for s in report.steps]
    assert step_names == [
        "retrieve_upcoming_fixtures",
        "retrieve_sportmonks_data",
        "update_database",
        "calculate_features",
        "generate_poisson_predictions",
        "generate_ml_predictions",
        "sync_sportmonks_predictions",
        "apply_ensemble_and_calibration",
        "retrieve_odds",
        "calculate_market_probability",
        "calculate_edge",
        "calculate_confidence",
        "rank_fixtures",
        "store_top_10",
        "send_daily_report",
    ]

    statuses = {s.name: s.status for s in report.steps}
    # the fixture was created purely from the mocked ingestion response,
    # with no prior history, so the ingestion/feature/odds steps succeed...
    assert statuses["retrieve_upcoming_fixtures"] == "ok"
    assert statuses["calculate_features"] == "ok"
    assert statuses["rank_fixtures"] == "ok"
    assert statuses["send_daily_report"] == "ok"
    # ...but ML/ensemble have no trained artifact yet - isolated failures,
    # not a crash of the whole pipeline.
    assert statuses["generate_ml_predictions"] == "failed"
    assert statuses["apply_ensemble_and_calibration"] == "failed"
    assert report.all_ok is False

    # the fixture itself was still ingested despite later steps failing
    assert db_session.get(Fixture, 1) is not None


def test_pipeline_full_happy_path_produces_a_ranked_selection(db_session, dummy_settings, tmp_path):
    # Seed prior history for both teams so Poisson/ML have something to
    # learn from, and pre-train/pre-fit the artifacts the pipeline needs.
    session = db_session
    session.add(League(id=8, name="Premier League"))
    session.add(Season(id=19735, league_id=8, name="2024/2025"))
    session.add(Team(id=1, name="Team 1"))
    session.add(Team(id=2, name="Team 2"))
    session.flush()

    rng = random.Random(7)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    for i in range(120):
        signal = rng.uniform(0, 1)
        label = 1 if signal > 0.5 else 0
        home_goals, away_goals = (2, 1) if label == 1 else (1, 0)
        fid = 1000 + i
        session.add(
            Fixture(
                id=fid, league_id=8, season_id=19735, kickoff=base + timedelta(hours=i),
                home_team_id=1, away_team_id=2, home_goals=home_goals, away_goals=away_goals, status="FT",
            )
        )
        session.flush()
        session.add(
            TeamFeatures(
                team_id=1, fixture_id=fid, is_home=True, as_of=base + timedelta(hours=i), computed_at=NOW,
                overall_last10_goals_scored=2.0 + signal, overall_last10_goals_conceded=1.0,
                venue_last10_goals_scored=2.0 + signal, venue_last10_goals_conceded=1.0,
            )
        )
        session.add(
            TeamFeatures(
                team_id=2, fixture_id=fid, is_home=False, as_of=base + timedelta(hours=i), computed_at=NOW,
                overall_last10_goals_scored=1.0, overall_last10_goals_conceded=1.0 + (1 - signal),
                venue_last10_goals_scored=1.0, venue_last10_goals_conceded=1.0 + (1 - signal),
            )
        )
        session.add(
            MatchFeatures(
                fixture_id=fid, league_avg_goals=2.5, league_home_goals_avg=1.5, league_away_goals_avg=1.2,
                computed_at=NOW,
            )
        )
        session.flush()
    session.add(
        LeagueModelPerformance(
            league_id=8, model_type="final", evaluation_window_start=date(2019, 1, 1), evaluation_window_end=date(2024, 1, 1),
            sample_size=300, league_reliability_score=0.9, is_eligible=True, computed_at=NOW,
        )
    )
    # flush (not commit) - this test's db_session fixture wraps everything in
    # an outer connection-level transaction rolled back at teardown; a real
    # commit() here would commit that transaction for real and permanently
    # leak this seed data into the test database. A flush is enough to make
    # it visible to later queries within this same session/transaction.
    session.flush()

    ml_dir = tmp_path / "ml"
    ensemble_dir = tmp_path / "ensemble"
    train_and_save_model(
        session, train_start=base, train_end=base + timedelta(days=4), val_end=base + timedelta(days=5),
        artifact_dir=ml_dir,
    )

    # compute poisson so an ensemble validation set has something to fit against
    from app.models.poisson_service import compute_and_store_poisson_predictions

    val_fixtures = session.execute(select(Fixture).where(Fixture.status == "FT")).scalars().all()
    compute_and_store_poisson_predictions(session, val_fixtures, commit=False)
    session.flush()
    fit_ensemble_and_calibration(session, val_start=base, val_end=base + timedelta(days=6), artifact_dir=ensemble_dir)

    client = _client(dummy_settings)
    # min_confidence=0.0 deliberately disables the confidence floor here:
    # with this test's toy synthetic data, Poisson and ML can legitimately
    # land on very different probabilities for the same fixture (nothing
    # ties their outputs together beyond both training on the same random
    # signal), which the confidence formula is *supposed* to penalize via
    # its model-agreement factor (see app/ranking/confidence.py - already
    # covered by test_confidence_and_scoring.py and
    # test_daily_ranking_service.py). This test's job is to prove the
    # pipeline's orchestration and data flow end to end, not to re-litigate
    # that threshold with numbers this synthetic setup can't reliably hit.
    report = run_daily_pipeline(
        session, client, ranking_date=RANKING_DATE, settings=dummy_settings,
        ml_artifact_dir=ml_dir, ensemble_artifact_dir=ensemble_dir, min_confidence=0.0,
    )

    statuses = {s.name: s.status for s in report.steps}
    assert statuses["generate_ml_predictions"] == "ok"
    assert statuses["apply_ensemble_and_calibration"] == "ok"

    rankings = session.execute(select(DailyRanking).where(DailyRanking.ranking_date == RANKING_DATE)).scalars().all()
    assert len(rankings) == 1
    assert rankings[0].fixture_id == 1
    assert 0.0 <= rankings[0].confidence_score <= 1.0

    prediction = session.execute(
        select(ModelPrediction).where(ModelPrediction.fixture_id == 1, ModelPrediction.model_version == "v1")
    ).scalar_one()
    assert prediction.poisson_probability is not None
    assert prediction.ml_probability is not None
    assert prediction.final_probability is not None
    assert prediction.calibration_method in ("platt", "isotonic", "none")
    assert prediction.ensemble_weights["poisson_probability"] > 0.0
