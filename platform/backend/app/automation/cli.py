"""Command-line entry point for the daily automation pipeline — the
single command a scheduler (n8n, cron, ...) needs to run.

Usage:
    python -m app.automation.cli run [--date 2024-08-17]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from app.automation.daily_pipeline import run_daily_pipeline
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.integrations.sportmonks.client import SportmonksClient

logger = logging.getLogger(__name__)


def _run(date_str: str | None) -> int:
    ranking_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now(timezone.utc).date()
    )

    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        with SportmonksClient(settings) as client:
            report = run_daily_pipeline(session, client, ranking_date=ranking_date, settings=settings)
    finally:
        session.close()

    for step in report.steps:
        logger.info("[%s] %s: %s", step.status.upper(), step.name, step.detail)

    logger.info("Daily pipeline for %s: %s", ranking_date, "all steps ok" if report.all_ok else "some steps failed")
    return 0 if report.all_ok else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Daily automation pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full daily pipeline for a date (default: today)")
    run_parser.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today (UTC)")

    args = parser.parse_args(argv)
    return _run(args.date)


if __name__ == "__main__":
    sys.exit(main())
