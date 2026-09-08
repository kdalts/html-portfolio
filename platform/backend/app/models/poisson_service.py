"""Orchestrates the Poisson model: reads Phase 4's team_features/
match_features for a fixture, computes an estimate, and stores it on
model_predictions.

No leakage guard is applied to `predicted_at` here, unlike
sportmonks_predictions/odds (app.ingestion.repository). That's
deliberate, not an oversight: the guard exists there because those tables
hold EXTERNAL data whose real-world availability timing is uncertain.
Here, `estimate_poisson`'s only inputs are team_features/match_features,
which Phase 4 already guarantees were computed using nothing but matches
strictly before the target fixture's kickoff. Running this computation
today for a fixture from 2020 produces the exact same number a genuine
2020 pre-match run would have, because the inputs are identical either
way — the leakage protection already happened upstream, at feature
computation time. `predicted_at` here just records when the computation
was run (useful for auditing), not a claim about data availability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.batch import BatchSummary
from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.models import repository
from app.models.constants import DEFAULT_MODEL_VERSION
from app.models.poisson import DEFAULT_WINDOW, estimate_poisson
from app.models.utils import row_to_dict

logger = logging.getLogger(__name__)


def compute_poisson_prediction_for_fixture(
    session: Session,
    fixture: Fixture,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    window: int = DEFAULT_WINDOW,
) -> dict | None:
    """Returns the model_predictions values dict, or None if Phase 4
    features aren't available yet for this fixture or don't carry enough
    history to produce a defensible estimate."""
    home_features = session.execute(
        select(TeamFeatures).where(
            TeamFeatures.fixture_id == fixture.id, TeamFeatures.team_id == fixture.home_team_id
        )
    ).scalar_one_or_none()
    away_features = session.execute(
        select(TeamFeatures).where(
            TeamFeatures.fixture_id == fixture.id, TeamFeatures.team_id == fixture.away_team_id
        )
    ).scalar_one_or_none()
    match_features = session.execute(
        select(MatchFeatures).where(MatchFeatures.fixture_id == fixture.id)
    ).scalar_one_or_none()

    if home_features is None or away_features is None or match_features is None:
        return None

    estimate = estimate_poisson(
        row_to_dict(home_features), row_to_dict(away_features), row_to_dict(match_features), window=window
    )
    if estimate is None:
        return None

    return {
        "fixture_id": fixture.id,
        "model_version": model_version,
        "expected_home_goals": estimate.expected_home_goals,
        "expected_away_goals": estimate.expected_away_goals,
        "poisson_probability": estimate.probability_over_2_5,
        "predicted_at": datetime.now(timezone.utc),
    }


def compute_and_store_poisson_predictions(
    session: Session,
    fixtures: list[Fixture],
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    window: int = DEFAULT_WINDOW,
    commit: bool = True,
) -> BatchSummary:
    summary = BatchSummary()
    for fixture in fixtures:
        summary.fetched += 1
        try:
            with session.begin_nested():
                values = compute_poisson_prediction_for_fixture(
                    session, fixture, model_version=model_version, window=window
                )
                if values is None:
                    raise ValueError(
                        "insufficient data for a Poisson estimate (features not computed yet, "
                        "or not enough team/league history)"
                    )
                repository.upsert_model_prediction(session, values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(fixture.id, exc)
            logger.warning("Failed to compute Poisson prediction for fixture %s: %s", fixture.id, exc)

    if commit:
        session.commit()
    return summary
