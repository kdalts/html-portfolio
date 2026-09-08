"""Command-line entry point for historical ingestion.

Usage:
    python -m app.ingestion.cli leagues
    python -m app.ingestion.cli fixtures --start 2019-08-01 --end 2019-08-31 [--with-statistics]

Reads SPORTMONKS_API_TOKEN / DATABASE_URL from the environment (via
Settings) — nothing here accepts credentials as arguments.
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.ingestion import service
from app.ingestion.sportmonks_reference import STATISTIC_TYPE_IDS, XG_TYPE_ID
from app.integrations.sportmonks.client import SportmonksClient

logger = logging.getLogger(__name__)


def _run_leagues() -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    with SportmonksClient(settings) as client:
        summary = service.ingest_leagues(client, session)
    session.close()
    logger.info("Leagues: fetched=%s upserted=%s failed=%s", summary.fetched, summary.upserted, summary.failed)
    for error in summary.errors:
        logger.warning(error)
    return 0 if summary else 1


def _run_fixtures(start: str, end: str, with_statistics: bool) -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    with SportmonksClient(settings) as client:
        summary = service.ingest_fixtures_between(
            client,
            session,
            start,
            end,
            ingest_statistics=with_statistics,
            statistic_type_ids=STATISTIC_TYPE_IDS if with_statistics else None,
            xg_type_id=XG_TYPE_ID if with_statistics else None,
        )
    session.close()
    logger.info(
        "Fixtures %s..%s: fetched=%s upserted=%s failed=%s", start, end, summary.fetched, summary.upserted, summary.failed
    )
    for error in summary.errors:
        logger.warning(error)
    return 0 if summary else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Historical Sportmonks data ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("leagues", help="Ingest all leagues")

    fixtures_parser = subparsers.add_parser("fixtures", help="Ingest fixtures in a date range")
    fixtures_parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    fixtures_parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    fixtures_parser.add_argument(
        "--with-statistics",
        action="store_true",
        help="Also ingest match_statistics/match_xg (requires configured type IDs in sportmonks_reference.py)",
    )

    args = parser.parse_args(argv)

    if args.command == "leagues":
        return _run_leagues()
    return _run_fixtures(args.start, args.end, args.with_statistics)


if __name__ == "__main__":
    sys.exit(main())
