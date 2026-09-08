from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.api.schemas import DailyRankingResponse, RankingEntry
from app.db.models.evaluation import DailyRanking
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Team
from app.db.models.predictions import ModelPrediction
from app.db.session import get_db

router = APIRouter(prefix="/api/rankings", tags=["rankings"])


@router.get("/daily", response_model=DailyRankingResponse)
def get_daily_ranking(ranking_date: date, db: Session = Depends(get_db)) -> DailyRankingResponse:
    home_team = aliased(Team)
    away_team = aliased(Team)

    rows = db.execute(
        select(DailyRanking, Fixture, home_team, away_team, League, ModelPrediction)
        .join(Fixture, Fixture.id == DailyRanking.fixture_id)
        .join(home_team, home_team.id == Fixture.home_team_id)
        .join(away_team, away_team.id == Fixture.away_team_id)
        .join(League, League.id == Fixture.league_id)
        .join(ModelPrediction, ModelPrediction.id == DailyRanking.model_prediction_id)
        .where(DailyRanking.ranking_date == ranking_date)
        .order_by(DailyRanking.rank)
    ).all()

    rankings = [
        RankingEntry(
            rank=ranking.rank,
            fixture_id=fixture.id,
            home_team=home.name,
            away_team=away.name,
            league_name=league.name,
            kickoff=fixture.kickoff,
            final_probability=ranking.final_probability,
            poisson_probability=prediction.poisson_probability,
            ml_probability=prediction.ml_probability,
            sportmonks_probability=prediction.sportmonks_probability,
            market_probability=ranking.market_probability,
            edge=ranking.edge,
            confidence_score=ranking.confidence_score,
            ranking_score=ranking.ranking_score,
        )
        for ranking, fixture, home, away, league, prediction in rows
    ]

    generated_at = rows[0][0].generated_at if rows else None
    return DailyRankingResponse(ranking_date=ranking_date, generated_at=generated_at, rankings=rankings)
