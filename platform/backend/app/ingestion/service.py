"""Orchestrates fetching from Sportmonks (via SportmonksClient) and
writing to the database (via the repository upserts), with per-item error
isolation so one malformed record never aborts an entire batch.

Historical bulk ingestion (`ingest_leagues`, `ingest_fixtures_between`,
and the optional statistics/xG it can pull inline) only ever writes
factual, post-hoc data: final scores, box-score stats, xG for matches that
have already been played. None of that is subject to the leakage guard —
it describes what already happened and is only ever consumed later as a
historical input to *future* predictions.

Sportmonks' own predictions and bookmaker odds are different: for a
fixture played long ago, there is no reliable way to know whether the
prediction/odds values Sportmonks returns today reflect what was known
before that fixture's kickoff. So they are deliberately NOT part of bulk
historical backfill. `ingest_prediction_for_fixture` /
`ingest_odds_for_fixture` exist for the operational, near-kickoff use case
instead (wired into automation in Phase 13): call them shortly before an
upcoming fixture kicks off, and the leakage guard enforces that the
`retrieved_at` timestamp is genuinely pre-kickoff.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.fixtures import Fixture
from app.ingestion import mappers, repository
from app.integrations.sportmonks.client import SportmonksClient

logger = logging.getLogger(__name__)

FIXTURES_DEFAULT_INCLUDE = "participants;scores;state;league;season"


@dataclass
class IngestionSummary:
    fetched: int = 0
    upserted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def record_error(self, identifier: object, exc: Exception) -> None:
        self.failed += 1
        self.errors.append(f"{identifier}: {exc}")

    def __bool__(self) -> bool:
        """A summary is "successful" if nothing failed."""
        return self.failed == 0


def ingest_leagues(client: SportmonksClient, session: Session, *, commit: bool = True) -> IngestionSummary:
    summary = IngestionSummary()
    for raw_league in client.get_leagues(include="country"):
        summary.fetched += 1
        identifier = raw_league.get("id", "?")
        try:
            values = mappers.map_league(raw_league)
            with session.begin_nested():
                repository.upsert_league(session, values)
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(identifier, exc)
            logger.warning("Failed to ingest league %s: %s", identifier, exc)
    if commit:
        session.commit()
    return summary


def _ingest_one_fixture(
    session: Session,
    raw_fixture: dict,
    *,
    ingest_statistics: bool,
    statistic_type_ids: dict[str, int | None],
    xg_type_id: int | None,
) -> None:
    raw_league = raw_fixture.get("league")
    if raw_league:
        repository.upsert_league(session, mappers.map_league(raw_league))
    raw_season = raw_fixture.get("season")
    if raw_season:
        repository.upsert_season(session, mappers.map_season(raw_season))
    for raw_participant in raw_fixture.get("participants") or []:
        repository.upsert_team(session, mappers.map_team(raw_participant))

    fixture_values = mappers.map_fixture(raw_fixture, logger=logger)
    repository.upsert_fixture(session, fixture_values)

    if ingest_statistics:
        for stat_row in mappers.map_match_statistics(raw_fixture, statistic_type_ids):
            repository.upsert_match_statistics(session, stat_row)
        for xg_row in mappers.map_match_xg(raw_fixture, xg_type_id):
            repository.upsert_match_xg(session, xg_row)


def ingest_fixtures_between(
    client: SportmonksClient,
    session: Session,
    start_date: str,
    end_date: str,
    *,
    include: str = FIXTURES_DEFAULT_INCLUDE,
    ingest_statistics: bool = False,
    statistic_type_ids: dict[str, int | None] | None = None,
    xg_type_id: int | None = None,
    commit: bool = True,
) -> IngestionSummary:
    """Backfill fixtures (+ their leagues/seasons/teams, and optionally
    post-match statistics/xG) for [start_date, end_date] ('YYYY-MM-DD').
    Never touches sportmonks_predictions or odds — see module docstring.
    """
    summary = IngestionSummary()
    effective_include = include
    if ingest_statistics and "statistics" not in effective_include:
        effective_include = f"{effective_include};statistics"

    for raw_fixture in client.get_fixtures_between(start_date, end_date, include=effective_include):
        summary.fetched += 1
        identifier = raw_fixture.get("id", "?")
        try:
            with session.begin_nested():
                _ingest_one_fixture(
                    session,
                    raw_fixture,
                    ingest_statistics=ingest_statistics,
                    statistic_type_ids=statistic_type_ids or {},
                    xg_type_id=xg_type_id,
                )
            summary.upserted += 1
        except Exception as exc:  # noqa: BLE001 - isolate and record, keep the batch going
            summary.record_error(identifier, exc)
            logger.warning("Failed to ingest fixture %s: %s", identifier, exc)

    if commit:
        session.commit()
    return summary


def ingest_prediction_for_fixture(
    session: Session,
    fixture: Fixture,
    raw_fixture: dict,
    *,
    over_2_5_type_id: int | None,
    btts_type_id: int | None = None,
    retrieved_at: datetime | None = None,
    commit: bool = True,
) -> bool:
    """Store Sportmonks' own Over 2.5 (and optionally BTTS) prediction for
    a fixture, at the moment it was retrieved. `fixture` must be the
    already-persisted Fixture row (its kickoff is the leakage-guard
    boundary). Returns False if there was nothing to store."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    values = mappers.map_sportmonks_prediction(
        raw_fixture,
        over_2_5_type_id=over_2_5_type_id,
        btts_type_id=btts_type_id,
        retrieved_at=retrieved_at,
    )
    if values is None:
        return False
    repository.upsert_sportmonks_prediction(session, values, kickoff=fixture.kickoff)
    if commit:
        session.commit()
    return True


def ingest_odds_for_fixture(
    session: Session,
    fixture: Fixture,
    raw_fixture: dict,
    *,
    market_id: int | None,
    retrieved_at: datetime | None = None,
    bookmaker_names: dict[int, str] | None = None,
    commit: bool = True,
) -> int:
    """Store Over/Under 2.5 odds snapshots for a fixture. `fixture` must
    be the already-persisted Fixture row. Returns the number of bookmaker
    rows stored."""
    retrieved_at = retrieved_at or datetime.now(timezone.utc)
    rows = mappers.map_odds(
        raw_fixture, market_id=market_id, retrieved_at=retrieved_at, bookmaker_names=bookmaker_names
    )
    for row in rows:
        repository.upsert_odds(session, row, kickoff=fixture.kickoff)
    if commit and rows:
        session.commit()
    return len(rows)
