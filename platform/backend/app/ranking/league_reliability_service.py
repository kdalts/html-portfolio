"""Orchestrates computing and storing league_model_performance from
Phase 7's backtest_results.

`model_type` here should be whichever model_type has actually been
backtested and is trusted as representative of what the daily ranking
will use (see docs/RANKING.md) — Phase 7's walk-forward loop currently
only evaluates 'poisson'/'ml' by default; extending it to backtest the
full ensemble/calibrated 'final' model per-fold is a larger, separate
piece of work (each fold would need its own ensemble-fitting validation
carve-out, distinct from ML's) and is flagged as a known limitation
rather than built here.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.common.batch import BatchSummary
from app.ranking import repository
from app.ranking.league_reliability import aggregate_league_metrics_from_backtest

logger = logging.getLogger(__name__)


def compute_and_store_league_reliability(
    session: Session,
    *,
    backtest_run_ids: list[str],
    model_type: str,
    evaluation_window_start: date,
    evaluation_window_end: date,
    commit: bool = True,
) -> BatchSummary:
    summary = BatchSummary()
    reliability_by_league = aggregate_league_metrics_from_backtest(
        session, backtest_run_ids=backtest_run_ids, model_type=model_type
    )
    now = datetime.now(timezone.utc)

    for league_id, reliability in reliability_by_league.items():
        summary.fetched += 1
        try:
            with session.begin_nested():
                repository.upsert_league_model_performance(
                    session,
                    {
                        "league_id": league_id,
                        "model_type": model_type,
                        "evaluation_window_start": evaluation_window_start,
                        "evaluation_window_end": evaluation_window_end,
                        "sample_size": reliability.sample_size,
                        "brier_score": reliability.brier_score,
                        "log_loss": reliability.log_loss,
                        "calibration_error": reliability.calibration_error,
                        "hit_rate": reliability.hit_rate,
                        "league_reliability_score": reliability.league_reliability_score,
                        "is_eligible": reliability.is_eligible,
                        "computed_at": now,
                    },
                )
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(league_id, exc)
            logger.warning("Failed to store league reliability for league %s: %s", league_id, exc)

    if commit:
        session.commit()
    return summary
