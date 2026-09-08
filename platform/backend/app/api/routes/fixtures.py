from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    FixtureDetailResponse,
    MatchFeatureSummary,
    ModelPredictionSummary,
    TeamRollingForm,
)
from app.db.models.evaluation import DailyRanking
from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Team
from app.db.models.predictions import ModelPrediction
from app.db.session import get_db
from app.models.constants import DEFAULT_MODEL_VERSION

router = APIRouter(prefix="/api/fixtures", tags=["fixtures"])


def _team_form(row: TeamFeatures | None, team_name: str) -> TeamRollingForm | None:
    if row is None:
        return None
    return TeamRollingForm(
        team_id=row.team_id,
        team_name=team_name,
        is_home=row.is_home,
        overall_last5_goals_scored=row.overall_last5_goals_scored,
        overall_last5_goals_conceded=row.overall_last5_goals_conceded,
        overall_last5_over_2_5_pct=row.overall_last5_over_2_5_pct,
        overall_last5_btts_pct=row.overall_last5_btts_pct,
        venue_last5_goals_scored=row.venue_last5_goals_scored,
        venue_last5_goals_conceded=row.venue_last5_goals_conceded,
        venue_last5_over_2_5_pct=row.venue_last5_over_2_5_pct,
        venue_last10_matches_played=row.venue_last10_matches_played,
        overall_last10_xg=row.overall_last10_xg,
        overall_last10_xga=row.overall_last10_xga,
    )


def _explain_prediction(prediction: ModelPrediction | None) -> str:
    if prediction is None:
        return "No prediction has been generated for this fixture yet."
    if prediction.final_probability is None:
        return "Component model probabilities are available, but the ensemble/calibration step hasn't run yet."
    weights = prediction.ensemble_weights or {}
    weight_text = ", ".join(f"{source.replace('_probability', '')}={weight:.2f}" for source, weight in weights.items())
    calibration = prediction.calibration_method or "none"
    return f"Ensemble weights: {weight_text or 'unavailable'}. Calibration method: {calibration}."


@router.get("/{fixture_id}", response_model=FixtureDetailResponse)
def get_fixture_detail(fixture_id: int, db: Session = Depends(get_db)) -> FixtureDetailResponse:
    fixture = db.get(Fixture, fixture_id)
    if fixture is None:
        raise HTTPException(status_code=404, detail="Fixture not found")

    home_team = db.get(Team, fixture.home_team_id)
    away_team = db.get(Team, fixture.away_team_id)
    league = db.get(League, fixture.league_id)

    home_features = db.execute(
        select(TeamFeatures).where(TeamFeatures.fixture_id == fixture_id, TeamFeatures.team_id == fixture.home_team_id)
    ).scalar_one_or_none()
    away_features = db.execute(
        select(TeamFeatures).where(TeamFeatures.fixture_id == fixture_id, TeamFeatures.team_id == fixture.away_team_id)
    ).scalar_one_or_none()
    match_features = db.execute(select(MatchFeatures).where(MatchFeatures.fixture_id == fixture_id)).scalar_one_or_none()
    prediction = db.execute(
        select(ModelPrediction).where(
            ModelPrediction.fixture_id == fixture_id, ModelPrediction.model_version == DEFAULT_MODEL_VERSION
        )
    ).scalar_one_or_none()
    # Most recent daily_rankings row for this fixture, if it was ever
    # ranked - the only place confidence_score/ranking_score are stored.
    ranking = db.execute(
        select(DailyRanking)
        .where(DailyRanking.fixture_id == fixture_id)
        .order_by(DailyRanking.ranking_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    prediction_summary = None
    if prediction is not None:
        prediction_summary = ModelPredictionSummary(
            model_version=prediction.model_version,
            expected_home_goals=prediction.expected_home_goals,
            expected_away_goals=prediction.expected_away_goals,
            poisson_probability=prediction.poisson_probability,
            ml_probability=prediction.ml_probability,
            sportmonks_probability=prediction.sportmonks_probability,
            raw_ensemble_probability=prediction.raw_ensemble_probability,
            ensemble_weights=prediction.ensemble_weights,
            calibration_method=prediction.calibration_method,
            final_probability=prediction.final_probability,
            market_probability=prediction.market_probability,
            market_odds_over=prediction.market_odds_over,
            market_odds_under=prediction.market_odds_under,
            edge=prediction.edge,
            explanation=_explain_prediction(prediction),
        )

    return FixtureDetailResponse(
        fixture_id=fixture.id,
        home_team=home_team.name if home_team else "Unknown",
        away_team=away_team.name if away_team else "Unknown",
        league_name=league.name if league else "Unknown",
        kickoff=fixture.kickoff,
        status=fixture.status,
        home_goals=fixture.home_goals,
        away_goals=fixture.away_goals,
        total_goals=fixture.total_goals,
        over_2_5=fixture.over_2_5,
        home_form=_team_form(home_features, home_team.name if home_team else "Unknown"),
        away_form=_team_form(away_features, away_team.name if away_team else "Unknown"),
        match_features=(
            MatchFeatureSummary(
                league_avg_goals=match_features.league_avg_goals,
                league_over_2_5_pct=match_features.league_over_2_5_pct,
                league_home_goals_avg=match_features.league_home_goals_avg,
                league_away_goals_avg=match_features.league_away_goals_avg,
                league_sample_size=match_features.league_sample_size,
                h2h_matches_played=match_features.h2h_matches_played,
                h2h_avg_total_goals=match_features.h2h_avg_total_goals,
                h2h_over_2_5_pct=match_features.h2h_over_2_5_pct,
                h2h_btts_pct=match_features.h2h_btts_pct,
                data_completeness_score=match_features.data_completeness_score,
            )
            if match_features is not None
            else None
        ),
        prediction=prediction_summary,
        confidence_score=ranking.confidence_score if ranking else None,
        ranking_score=ranking.ranking_score if ranking else None,
    )
