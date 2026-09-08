from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import LeaguePerformanceEntry
from app.db.models.evaluation import LeagueModelPerformance
from app.db.models.leagues_teams import League
from app.db.session import get_db

router = APIRouter(prefix="/api/leagues", tags=["leagues"])


@router.get("/performance", response_model=list[LeaguePerformanceEntry])
def get_league_performance(db: Session = Depends(get_db)) -> list[LeaguePerformanceEntry]:
    rows = db.execute(
        select(LeagueModelPerformance, League)
        .join(League, League.id == LeagueModelPerformance.league_id)
        .order_by(LeagueModelPerformance.league_reliability_score.desc())
    ).all()

    return [
        LeaguePerformanceEntry(
            league_id=performance.league_id,
            league_name=league.name,
            model_type=performance.model_type,
            evaluation_window_start=performance.evaluation_window_start,
            evaluation_window_end=performance.evaluation_window_end,
            sample_size=performance.sample_size,
            brier_score=performance.brier_score,
            log_loss=performance.log_loss,
            calibration_error=performance.calibration_error,
            hit_rate=performance.hit_rate,
            league_reliability_score=performance.league_reliability_score,
            is_eligible=performance.is_eligible,
        )
        for performance, league in rows
    ]
