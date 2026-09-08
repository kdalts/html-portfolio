"""Command-line entry point for feature computation.

Usage:
    python -m app.features.cli build --start 2019-08-01 --end 2025-08-01

Computes team_features/match_features for every fixture whose kickoff
falls in [start, end), regardless of the fixture's own status — an
upcoming fixture needs features computed for it (for the daily ranking)
just as much as a historical one does (for training/backtesting).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models.fixtures import Fixture
from app.db.session import get_session_factory
from app.features.service import compute_and_store_features_for_fixtures

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _run_build(start: str, end: str) -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        fixtures = (
            session.execute(
                select(Fixture)
                .where(Fixture.kickoff >= _parse_date(start), Fixture.kickoff < _parse_date(end))
                .order_by(Fixture.kickoff)
            )
            .scalars()
            .all()
        )
        summary = compute_and_store_features_for_fixtures(session, list(fixtures))
    finally:
        session.close()

    logger.info(
        "Features %s..%s: fetched=%s upserted=%s failed=%s", start, end, summary.fetched, summary.upserted, summary.failed
    )
    for error in summary.errors:
        logger.warning(error)
    return 0 if summary else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Feature computation for fixtures")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Compute features for fixtures kicking off in a date range")
    build_parser.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    build_parser.add_argument("--end", required=True, help="YYYY-MM-DD (exclusive)")

    args = parser.parse_args(argv)
    return _run_build(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main())
