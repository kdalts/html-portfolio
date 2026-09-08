"""Builds the daily Top N: fetches upcoming fixtures for a date, removes
any where data is insufficient, no prediction is available, the league
isn't reliable enough, or confidence is too low, computes
confidence_score and ranking_score for what's left, ranks them, and
stores the top N in daily_rankings.

daily_rankings is written delete-then-insert per ranking_date rather than
upserted: which fixtures qualify (and their ranks) can change from one
run to the next as new data arrives, so there's no stable per-row key to
upsert against — clearing the day's prior rows and inserting the fresh
set is simpler and correct. Both runs happen in the same transaction, so
a failure leaves the previous day's ranking intact rather than half-
overwritten.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models.evaluation import DailyRanking, LeagueModelPerformance
from app.db.models.features import MatchFeatures
from app.db.models.fixtures import Fixture
from app.db.models.predictions import ModelPrediction
from app.models.constants import DEFAULT_MODEL_VERSION
from app.ranking.confidence import compute_confidence_score
from app.ranking.scoring import compute_ranking_score

logger = logging.getLogger(__name__)

DEFAULT_TOP_N = 10
DEFAULT_MIN_CONFIDENCE = 0.15  # a documented, tunable floor - not yet tuned against real outcomes


def _day_bounds(ranking_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(ranking_date, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _latest_league_reliability(session: Session, league_id: int, model_type: str) -> LeagueModelPerformance | None:
    return session.execute(
        select(LeagueModelPerformance)
        .where(LeagueModelPerformance.league_id == league_id, LeagueModelPerformance.model_type == model_type)
        .order_by(LeagueModelPerformance.evaluation_window_end.desc())
        .limit(1)
    ).scalar_one_or_none()


def build_daily_ranking(
    session: Session,
    *,
    ranking_date: date,
    model_version: str = DEFAULT_MODEL_VERSION,
    reliability_model_type: str = "final",
    top_n: int = DEFAULT_TOP_N,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    commit: bool = True,
) -> dict:
    """Returns a summary dict: {"considered": int, "qualified": int,
    "ranked": int, "excluded": {fixture_id: reason}}."""
    start, end = _day_bounds(ranking_date)
    fixtures = (
        session.execute(
            select(Fixture).where(Fixture.kickoff >= start, Fixture.kickoff < end, Fixture.status == "NS")
        )
        .scalars()
        .all()
    )

    excluded: dict[int, str] = {}
    candidates: list[tuple[Fixture, ModelPrediction, LeagueModelPerformance, float, float]] = []

    for fixture in fixtures:
        prediction = session.execute(
            select(ModelPrediction).where(
                ModelPrediction.fixture_id == fixture.id, ModelPrediction.model_version == model_version
            )
        ).scalar_one_or_none()
        if prediction is None or prediction.final_probability is None:
            excluded[fixture.id] = "no final_probability available"
            continue

        league_reliability = _latest_league_reliability(session, fixture.league_id, reliability_model_type)
        if league_reliability is None or not league_reliability.is_eligible:
            excluded[fixture.id] = "league not eligible (insufficient or unreliable historical performance)"
            continue

        match_features = session.execute(
            select(MatchFeatures).where(MatchFeatures.fixture_id == fixture.id)
        ).scalar_one_or_none()
        if match_features is None:
            excluded[fixture.id] = "no features computed for this fixture"
            continue

        available_probabilities = [
            p
            for p in (prediction.poisson_probability, prediction.ml_probability, prediction.sportmonks_probability)
            if p is not None
        ]
        confidence = compute_confidence_score(
            data_completeness_score=match_features.data_completeness_score,
            league_reliability_score=league_reliability.league_reliability_score,
            available_probabilities=available_probabilities,
        )
        if confidence < min_confidence:
            excluded[fixture.id] = f"confidence {confidence:.3f} below threshold {min_confidence}"
            continue

        ranking_score = compute_ranking_score(
            final_probability=prediction.final_probability, confidence_score=confidence, edge=prediction.edge
        )
        candidates.append((fixture, prediction, league_reliability, confidence, ranking_score))

    candidates.sort(key=lambda c: c[4], reverse=True)
    top_candidates = candidates[:top_n]

    session.execute(delete(DailyRanking).where(DailyRanking.ranking_date == ranking_date))

    now = datetime.now(timezone.utc)
    for rank, (fixture, prediction, league_reliability, confidence, score) in enumerate(top_candidates, start=1):
        session.add(
            DailyRanking(
                ranking_date=ranking_date,
                fixture_id=fixture.id,
                model_prediction_id=prediction.id,
                rank=rank,
                ranking_score=score,
                final_probability=prediction.final_probability,
                confidence_score=confidence,
                market_probability=prediction.market_probability,
                edge=prediction.edge,
                league_reliability_score=league_reliability.league_reliability_score,
                generated_at=now,
            )
        )

    if commit:
        session.commit()

    return {
        "considered": len(fixtures),
        "qualified": len(candidates),
        "ranked": len(top_candidates),
        "excluded": excluded,
    }
