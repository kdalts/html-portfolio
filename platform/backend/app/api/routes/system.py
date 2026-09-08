from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import SystemHealthResponse
from app.core.config import get_settings
from app.db.models.evaluation import DailyRanking
from app.db.models.features import MatchFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Team
from app.db.models.predictions import ModelPrediction
from app.db.session import get_db

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health", response_model=SystemHealthResponse)
def get_system_health(db: Session = Depends(get_db)) -> SystemHealthResponse:
    counts = {
        "leagues": db.execute(select(func.count()).select_from(League)).scalar_one(),
        "teams": db.execute(select(func.count()).select_from(Team)).scalar_one(),
        "fixtures": db.execute(select(func.count()).select_from(Fixture)).scalar_one(),
        "predictions": db.execute(select(func.count()).select_from(ModelPrediction)).scalar_one(),
        "rankings": db.execute(select(func.count()).select_from(DailyRanking)).scalar_one(),
    }

    latest = {
        "last_fixture_ingested_at": db.execute(select(func.max(Fixture.updated_at))).scalar_one(),
        "last_features_computed_at": db.execute(select(func.max(MatchFeatures.computed_at))).scalar_one(),
        "last_prediction_at": db.execute(select(func.max(ModelPrediction.predicted_at))).scalar_one(),
        "last_ranking_generated_at": db.execute(select(func.max(DailyRanking.generated_at))).scalar_one(),
    }

    try:
        sportmonks_configured = bool(get_settings().sportmonks_api_token)
    except Exception:  # noqa: BLE001 - Settings() itself raises if misconfigured; that IS the answer
        sportmonks_configured = False

    return SystemHealthResponse(
        status="ok",
        database_connected=True,  # reaching this line means every query above already succeeded
        sportmonks_token_configured=sportmonks_configured,
        counts=counts,
        latest=latest,
    )
