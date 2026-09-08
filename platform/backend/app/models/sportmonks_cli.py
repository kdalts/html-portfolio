"""Command-line entry point for syncing Sportmonks predictions into
model_predictions.

Usage:
    python -m app.models.sportmonks_cli sync --start 2024-08-01 --end 2024-09-01
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
from app.models.sportmonks_service import sync_and_store_sportmonks_predictions

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _run_sync(start: str, end: str) -> int:
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
        summary = sync_and_store_sportmonks_predictions(session, list(fixtures))
    finally:
        session.close()

    logger.info(
        "Sportmonks sync %s..%s: fetched=%s upserted=%s failed=%s",
        start,
        end,
        summary.fetched,
        summary.upserted,
        summary.failed,
    )
    for error in summary.errors:
        logger.warning(error)
    return 0 if summary else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Sync Sportmonks predictions into model_predictions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Sync fixtures in a date range")
    sync_parser.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    sync_parser.add_argument("--end", required=True, help="YYYY-MM-DD (exclusive)")

    args = parser.parse_args(argv)
    return _run_sync(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main())
