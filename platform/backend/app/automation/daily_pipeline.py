"""The daily automation pipeline — the spec's twelve AUTOMATION steps,
run in order, with per-step failure isolation: one step failing is
recorded in the run report and does not prevent the rest of the pipeline
from attempting to run, consistent with every batch operation elsewhere
in this codebase.

Model training (Phase 6), backtesting (Phase 7), and league-reliability
scoring (Phase 11) are deliberately NOT part of this daily pipeline —
they are periodic/on-demand jobs (see docs/DEPLOYMENT.md), not something
that needs to re-run every day. This pipeline assumes a trained ML
artifact and a fitted ensemble/calibration config already exist, and that
league_model_performance has already been computed at least once; if any
of those are missing, the corresponding step is recorded as failed in the
run report (with a clear reason) rather than crashing the whole run.

Some of the spec's twelve steps don't correspond to a separate action in
this codebase's actual data model — e.g. "calculate edge" is a PostgreSQL
generated column (Phase 2), not a computation this pipeline performs, and
"calculate confidence" / "store the Top 10" both happen inside the single
`build_daily_ranking` call (Phase 11), since confidence_score only exists
on daily_rankings rows. Rather than fabricate a separate no-op action for
these, they're recorded in the run report with a detail string explaining
where the real work happens — see each step's comment below.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automation.report import generate_daily_report, send_report
from app.core.config import Settings, get_settings
from app.db.models.fixtures import Fixture
from app.features.service import compute_and_store_features_for_fixtures
from app.ingestion import service as ingestion_service
from app.ingestion.sportmonks_reference import (
    ODDS_MARKET_ID_OVER_UNDER,
    PREDICTION_TYPE_ID_BTTS,
    PREDICTION_TYPE_ID_OVER_UNDER_2_5,
)
from app.integrations.sportmonks.client import SportmonksClient
from app.models.constants import DEFAULT_MODEL_VERSION
from app.models.ensemble_service import DEFAULT_ARTIFACT_DIR as DEFAULT_ENSEMBLE_ARTIFACT_DIR
from app.models.ensemble_service import apply_ensemble_and_calibration_for_fixtures
from app.models.ml_service import DEFAULT_ARTIFACT_DIR as DEFAULT_ML_ARTIFACT_DIR
from app.models.ml_service import compute_and_store_ml_predictions
from app.models.odds_service import sync_and_store_market_data
from app.models.poisson_service import compute_and_store_poisson_predictions
from app.models.sportmonks_service import sync_and_store_sportmonks_predictions
from app.ranking.daily_ranking_service import DEFAULT_MIN_CONFIDENCE, DEFAULT_TOP_N, build_daily_ranking

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    name: str
    status: str  # "ok" | "failed"
    detail: str = ""


@dataclass
class DailyPipelineReport:
    ranking_date: date
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[StepResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(step.status == "ok" for step in self.steps)


def _fetch_upcoming_fixtures(session: Session, ranking_date: date) -> list[Fixture]:
    start = datetime.combine(ranking_date, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(ranking_date, datetime.max.time(), tzinfo=timezone.utc)
    return list(
        session.execute(
            select(Fixture).where(Fixture.kickoff >= start, Fixture.kickoff <= end, Fixture.status == "NS")
        )
        .scalars()
        .all()
    )


def run_daily_pipeline(
    session: Session,
    client: SportmonksClient,
    *,
    ranking_date: date,
    settings: Settings | None = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    ml_artifact_dir: Path = DEFAULT_ML_ARTIFACT_DIR,
    ensemble_artifact_dir: Path = DEFAULT_ENSEMBLE_ARTIFACT_DIR,
    top_n: int = DEFAULT_TOP_N,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    reliability_model_type: str = "final",
    commit: bool = True,
) -> DailyPipelineReport:
    """`settings` defaults to get_settings() (the normal CLI path) but can
    be passed explicitly so callers (tests included) aren't tied to
    process-wide environment variables.

    `reliability_model_type` defaults to "final" (the fully-calibrated
    ensemble output - the intended production signal per the spec) but is
    overridable: league_model_performance only has rows for whichever
    model_type(s) have actually been through app.ranking.cli
    league-reliability, itself downstream of a walk-forward backtest for
    that model_type. Walk-forward backtesting the 'final' ensemble model
    per fold is a larger feature not yet built (see Phase 11's remaining
    risks) - until then, a real deployment that has only backtested
    'poisson'/'ml' should pass one of those here, or every league will
    look "no data" and nothing will ever rank, regardless of how good the
    underlying poisson/ml reliability scores actually are.

    `commit` defaults to True so a real automation run persists each step's
    progress as it goes (a later step failing shouldn't roll back earlier,
    independently-valid work). Tests pass `commit=False` so the whole run
    stays inside the test fixture's outer transaction and rolls back cleanly
    at teardown - calling session.commit() on that fixture's session would
    otherwise commit the underlying connection for real and defeat its
    rollback-based isolation."""
    settings = settings or get_settings()
    report = DailyPipelineReport(ranking_date=ranking_date, started_at=datetime.now(timezone.utc))

    def _run_step(name: str, fn) -> None:
        try:
            detail = fn()
            report.steps.append(StepResult(name=name, status="ok", detail=detail or ""))
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the pipeline going
            logger.warning("Daily pipeline step %r failed: %s", name, exc)
            report.steps.append(StepResult(name=name, status="failed", detail=str(exc)))

    date_str = ranking_date.isoformat()
    next_day_str = date.fromordinal(ranking_date.toordinal() + 1).isoformat()

    # 1. Retrieve upcoming fixtures
    def step_fixtures():
        summary = ingestion_service.ingest_fixtures_between(client, session, date_str, next_day_str, commit=commit)
        return f"fetched={summary.fetched} upserted={summary.upserted} failed={summary.failed}"

    _run_step("retrieve_upcoming_fixtures", step_fixtures)

    upcoming = _fetch_upcoming_fixtures(session, ranking_date)

    # 2. Retrieve required Sportmonks data (predictions, near-kickoff)
    def step_sportmonks_predictions():
        stored = 0
        for fixture in upcoming:
            raw_fixture = client.get_fixture(fixture.id, include="predictions")
            if ingestion_service.ingest_prediction_for_fixture(
                session,
                fixture,
                raw_fixture,
                over_2_5_type_id=PREDICTION_TYPE_ID_OVER_UNDER_2_5,
                btts_type_id=PREDICTION_TYPE_ID_BTTS,
                commit=False,
            ):
                stored += 1
        if commit:
            session.commit()
        else:
            session.flush()
        return f"stored={stored}/{len(upcoming)} (requires PREDICTION_TYPE_ID_OVER_UNDER_2_5 configured)"

    _run_step("retrieve_sportmonks_data", step_sportmonks_predictions)

    # 3. Update the database (implicit: every ingestion call above already writes through)
    report.steps.append(
        StepResult(name="update_database", status="ok", detail="performed inline by the ingestion steps above")
    )

    # 4. Calculate features
    def step_features():
        summary = compute_and_store_features_for_fixtures(session, upcoming, commit=commit)
        return f"fetched={summary.fetched} upserted={summary.upserted} failed={summary.failed}"

    _run_step("calculate_features", step_features)

    # 5. Generate predictions. Split into four independently-isolated
    # sub-steps rather than one bundled call: compute_and_store_ml_predictions
    # raises immediately (not per-fixture) if no trained artifact exists yet,
    # and bundling it with the others would let that one missing
    # prerequisite silently prevent sportmonks-sync/ensemble from ever
    # running, even though neither depends on it.
    def step_poisson():
        summary = compute_and_store_poisson_predictions(session, upcoming, model_version=model_version, commit=commit)
        return f"upserted={summary.upserted} failed={summary.failed} (of {len(upcoming)})"

    _run_step("generate_poisson_predictions", step_poisson)

    def step_ml():
        summary = compute_and_store_ml_predictions(
            session, upcoming, model_version=model_version, artifact_dir=ml_artifact_dir, commit=commit
        )
        return f"upserted={summary.upserted} failed={summary.failed} (of {len(upcoming)})"

    _run_step("generate_ml_predictions", step_ml)

    def step_sportmonks_sync():
        summary = sync_and_store_sportmonks_predictions(session, upcoming, model_version=model_version, commit=commit)
        return f"upserted={summary.upserted} failed={summary.failed} (of {len(upcoming)})"

    _run_step("sync_sportmonks_predictions", step_sportmonks_sync)

    def step_ensemble():
        summary = apply_ensemble_and_calibration_for_fixtures(
            session, upcoming, model_version=model_version, artifact_dir=ensemble_artifact_dir, commit=commit
        )
        return f"upserted={summary.upserted} failed={summary.failed} (of {len(upcoming)})"

    _run_step("apply_ensemble_and_calibration", step_ensemble)

    # 6. Retrieve odds
    def step_odds():
        stored = 0
        for fixture in upcoming:
            raw_fixture = client.get_fixture(fixture.id, include="odds")
            stored += ingestion_service.ingest_odds_for_fixture(
                session, fixture, raw_fixture, market_id=ODDS_MARKET_ID_OVER_UNDER, commit=False
            )
        if commit:
            session.commit()
        else:
            session.flush()
        return f"snapshots_stored={stored} (requires ODDS_MARKET_ID_OVER_UNDER configured)"

    _run_step("retrieve_odds", step_odds)

    # 7. Calculate market probability
    def step_market():
        summary = sync_and_store_market_data(session, upcoming, model_version=model_version, commit=commit)
        return f"fetched={summary.fetched} upserted={summary.upserted} failed={summary.failed}"

    _run_step("calculate_market_probability", step_market)

    # 8. Calculate edge - a PostgreSQL generated column (Phase 2), not a
    # separate computation; it follows automatically once
    # final_probability and market_probability are both set.
    report.steps.append(
        StepResult(name="calculate_edge", status="ok", detail="generated column, computed automatically by PostgreSQL")
    )

    # 9. Calculate confidence - only stored on daily_rankings rows
    # (Phase 2 schema), so it's computed inside step 10, not separately.
    report.steps.append(
        StepResult(name="calculate_confidence", status="ok", detail="computed inline as part of rank_fixtures below")
    )

    # 10. Rank fixtures / 11. Store the Top 10 - one call does both.
    def step_ranking():
        result = build_daily_ranking(
            session,
            ranking_date=ranking_date,
            model_version=model_version,
            reliability_model_type=reliability_model_type,
            top_n=top_n,
            min_confidence=min_confidence,
            commit=commit,
        )
        return f"considered={result['considered']} qualified={result['qualified']} ranked={result['ranked']}"

    _run_step("rank_fixtures", step_ranking)
    report.steps.append(
        StepResult(name="store_top_10", status="ok", detail="performed inline by rank_fixtures above")
    )

    # 12. Send the daily report
    def step_report():
        report_text = generate_daily_report(session, ranking_date)
        delivered = send_report(report_text, webhook_url=settings.daily_report_webhook_url)
        return "delivered to webhook" if delivered else "logged only (no webhook configured)"

    _run_step("send_daily_report", step_report)

    report.finished_at = datetime.now(timezone.utc)
    return report


def run_pipeline_for_date_range(
    session: Session,
    client: SportmonksClient,
    *,
    start_date: date,
    days: int,
    settings: Settings | None = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    ml_artifact_dir: Path = DEFAULT_ML_ARTIFACT_DIR,
    ensemble_artifact_dir: Path = DEFAULT_ENSEMBLE_ARTIFACT_DIR,
    top_n: int = DEFAULT_TOP_N,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    reliability_model_type: str = "final",
    commit: bool = True,
) -> list[DailyPipelineReport]:
    """Runs `run_daily_pipeline` once per day across [start_date, start_date +
    days) - lets an operator pre-populate a week's (or any N days') worth of
    fixtures/features/predictions/rankings in one command, rather than
    needing to run this fresh every single day. Each day is fully
    independent: one day's failures (or an empty matchday) don't stop the
    rest from running, the same failure-isolation philosophy as every step
    inside a single day's run.

    Real caveat, not a bug: predictions/odds pulled this far ahead of
    kickoff are inherently less final than pulling them the day of - both
    Sportmonks' own predictions and bookmaker lines commonly firm up in the
    days immediately before a match. This is still leakage-safe (every
    write here happens strictly pre-kickoff, same guard as everywhere else
    in this codebase) - it's a data-freshness tradeoff, not a data-integrity
    one, and it's the deliberate point of running this less often."""
    reports: list[DailyPipelineReport] = []
    for offset in range(days):
        ranking_date = start_date + timedelta(days=offset)
        report = run_daily_pipeline(
            session,
            client,
            ranking_date=ranking_date,
            settings=settings,
            model_version=model_version,
            ml_artifact_dir=ml_artifact_dir,
            ensemble_artifact_dir=ensemble_artifact_dir,
            top_n=top_n,
            min_confidence=min_confidence,
            reliability_model_type=reliability_model_type,
            commit=commit,
        )
        reports.append(report)
    return reports
