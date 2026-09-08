"""Import every ORM model so Base.metadata is complete (required for
Alembic autogenerate and for Base.metadata.create_all in tests)."""

from app.db.base import Base
from app.db.models.evaluation import BacktestResult, DailyRanking, LeagueModelPerformance
from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import MatchStatistics, MatchXG, Odds, SportmonksPrediction
from app.db.models.predictions import ModelPrediction

__all__ = [
    "Base",
    "League",
    "Team",
    "Season",
    "Fixture",
    "MatchStatistics",
    "MatchXG",
    "SportmonksPrediction",
    "Odds",
    "TeamFeatures",
    "MatchFeatures",
    "ModelPrediction",
    "BacktestResult",
    "LeagueModelPerformance",
    "DailyRanking",
]
