"""Integrates market odds into the unified model_predictions row, so
Phase 2's generated `edge` column (final_probability - market_probability)
becomes meaningful.

Uses the already-ingested, leakage-guarded `odds` table (Phase 3's
ingest_odds_for_fixture enforces retrieved_at < kickoff at ingestion
time — nothing here can introduce new leakage). `market_probability` is
ALWAYS the de-vigged figure (computed on the `odds` table itself by
Postgres), never the raw `over_implied_probability` that still includes
the bookmaker's margin — per spec, a model probability beating the raw
implied probability is not by itself evidence of value; only a gap
against the de-vigged market_probability is a genuine edge signal. This
module never reads `over_implied_probability`/`under_implied_probability`
at all, by construction.

Aggregates across whichever bookmakers have odds for this fixture (the
latest snapshot per bookmaker), rather than trusting a single source. A
snapshot is rejected as implausible (a rough data-quality guard against
stale or malformed odds feeding a misleading edge number) if its
overround falls outside a sane range.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.batch import BatchSummary
from app.db.models.fixtures import Fixture
from app.db.models.match_data import Odds
from app.db.models.predictions import ModelPrediction
from app.models import repository
from app.models.constants import DEFAULT_MODEL_VERSION

logger = logging.getLogger(__name__)

MIN_PLAUSIBLE_OVERROUND = 1.0
MAX_PLAUSIBLE_OVERROUND = 1.30


@dataclass(frozen=True)
class MarketSnapshot:
    market_probability: float
    market_odds_over: float
    market_odds_under: float
    bookmaker_count: int
    odds_id: int | None  # set only when exactly one bookmaker informed this snapshot


def _latest_snapshot_per_bookmaker(session: Session, fixture_id: int) -> list[Odds]:
    rows = (
        session.execute(select(Odds).where(Odds.fixture_id == fixture_id).order_by(Odds.retrieved_at))
        .scalars()
        .all()
    )
    latest: dict[str, Odds] = {}
    for row in rows:
        latest[row.bookmaker] = row  # later (larger retrieved_at) rows overwrite earlier ones
    return list(latest.values())


def _is_plausible(row: Odds) -> bool:
    return row.market_probability is not None and MIN_PLAUSIBLE_OVERROUND < row.overround < MAX_PLAUSIBLE_OVERROUND


def build_market_snapshot(session: Session, fixture_id: int) -> MarketSnapshot | None:
    """None if no bookmaker has plausible odds for this fixture — never a
    fabricated consensus from bad data."""
    candidates = [row for row in _latest_snapshot_per_bookmaker(session, fixture_id) if _is_plausible(row)]
    if not candidates:
        return None

    n = len(candidates)
    return MarketSnapshot(
        market_probability=sum(r.market_probability for r in candidates) / n,
        market_odds_over=sum(r.over_odds for r in candidates) / n,
        market_odds_under=sum(r.under_odds for r in candidates) / n,
        bookmaker_count=n,
        odds_id=candidates[0].id if n == 1 else None,
    )


def sync_market_data_for_fixture(
    session: Session, fixture: Fixture, *, model_version: str = DEFAULT_MODEL_VERSION
) -> dict | None:
    snapshot = build_market_snapshot(session, fixture.id)
    if snapshot is None:
        return None

    existing = session.execute(
        select(ModelPrediction).where(
            ModelPrediction.fixture_id == fixture.id, ModelPrediction.model_version == model_version
        )
    ).scalar_one_or_none()
    # Carried forward when the row already exists (see Phase 8's fix):
    # Postgres validates NOT NULL columns against the proposed INSERT row
    # even when ON CONFLICT DO UPDATE ends up running instead.
    predicted_at = existing.predicted_at if existing is not None else datetime.now(timezone.utc)

    return {
        "fixture_id": fixture.id,
        "model_version": model_version,
        "predicted_at": predicted_at,
        "market_probability": snapshot.market_probability,
        "market_odds_over": snapshot.market_odds_over,
        "market_odds_under": snapshot.market_odds_under,
        "odds_id": snapshot.odds_id,
    }


def sync_and_store_market_data(
    session: Session,
    fixtures: list[Fixture],
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    commit: bool = True,
) -> BatchSummary:
    summary = BatchSummary()
    for fixture in fixtures:
        summary.fetched += 1
        try:
            with session.begin_nested():
                values = sync_market_data_for_fixture(session, fixture, model_version=model_version)
                if values is None:
                    raise ValueError("no plausible odds snapshot available for this fixture")
                repository.upsert_model_prediction(session, values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(fixture.id, exc)
            logger.warning("Failed to sync market data for fixture %s: %s", fixture.id, exc)

    if commit:
        session.commit()
    return summary
