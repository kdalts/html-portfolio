from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import BacktestRunSummary, ModelPerformanceEntry, ProbabilityBandEntry
from app.db.models.evaluation import BacktestResult
from app.db.session import get_db

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.get("/runs", response_model=list[BacktestRunSummary])
def list_backtest_runs(db: Session = Depends(get_db)) -> list[BacktestRunSummary]:
    """Every stored (backtest_run_id, model_type) pair with its overall
    metrics and probability-band breakdown - the historical backtest view."""
    rows = (
        db.execute(select(BacktestResult).order_by(BacktestResult.test_end_date.desc(), BacktestResult.backtest_run_id))
        .scalars()
        .all()
    )

    grouped: dict[tuple[str, str], list[BacktestResult]] = {}
    for row in rows:
        grouped.setdefault((row.backtest_run_id, row.model_type), []).append(row)

    summaries = []
    for (run_id, model_type), group in grouped.items():
        overall_row = next((r for r in group if r.segment_type == "overall"), None)
        band_rows = [r for r in group if r.segment_type == "probability_band"]
        if overall_row is None:
            continue

        summaries.append(
            BacktestRunSummary(
                backtest_run_id=run_id,
                model_type=model_type,
                train_start_date=overall_row.train_start_date,
                train_end_date=overall_row.train_end_date,
                test_start_date=overall_row.test_start_date,
                test_end_date=overall_row.test_end_date,
                overall=ModelPerformanceEntry(
                    model_type=model_type,
                    backtest_run_id=run_id,
                    test_start_date=overall_row.test_start_date,
                    test_end_date=overall_row.test_end_date,
                    sample_size=overall_row.sample_size,
                    log_loss=overall_row.log_loss,
                    brier_score=overall_row.brier_score,
                    roc_auc=overall_row.roc_auc,
                    accuracy=overall_row.accuracy,
                    precision_score=overall_row.precision_score,
                    recall_score=overall_row.recall_score,
                    calibration_error=overall_row.calibration_error,
                    hit_rate=overall_row.hit_rate,
                ),
                probability_bands=[
                    ProbabilityBandEntry(
                        band=b.segment_value,
                        predicted_probability_mean=b.predicted_probability_mean,
                        actual_frequency=b.actual_frequency,
                        sample_size=b.sample_size,
                    )
                    for b in band_rows
                ],
            )
        )

    summaries.sort(key=lambda s: (s.test_end_date, s.backtest_run_id), reverse=True)
    return summaries
