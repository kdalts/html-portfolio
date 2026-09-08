from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ModelPerformanceEntry
from app.db.models.evaluation import BacktestResult
from app.db.session import get_db

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("/performance", response_model=list[ModelPerformanceEntry])
def get_model_performance(db: Session = Depends(get_db)) -> list[ModelPerformanceEntry]:
    """The most recent walk-forward fold's overall metrics, per model_type."""
    rows = (
        db.execute(
            select(BacktestResult)
            .where(BacktestResult.segment_type == "overall")
            .order_by(BacktestResult.model_type, BacktestResult.test_end_date.desc())
        )
        .scalars()
        .all()
    )

    latest_per_model: dict[str, BacktestResult] = {}
    for row in rows:
        if row.model_type not in latest_per_model:
            latest_per_model[row.model_type] = row  # first seen per model_type is the most recent, given ordering

    return [
        ModelPerformanceEntry(
            model_type=row.model_type,
            backtest_run_id=row.backtest_run_id,
            test_start_date=row.test_start_date,
            test_end_date=row.test_end_date,
            sample_size=row.sample_size,
            log_loss=row.log_loss,
            brier_score=row.brier_score,
            roc_auc=row.roc_auc,
            accuracy=row.accuracy,
            precision_score=row.precision_score,
            recall_score=row.recall_score,
            calibration_error=row.calibration_error,
            hit_rate=row.hit_rate,
        )
        for row in latest_per_model.values()
    ]
