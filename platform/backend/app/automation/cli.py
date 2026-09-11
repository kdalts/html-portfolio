"""Command-line entry point for the daily automation pipeline — the
single command a scheduler (n8n, cron, ...) needs to run.

Usage:
    python -m app.automation.cli run [--date 2024-08-17] [--days 7] [--reliability-model-type final]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from app.automation.daily_pipeline import run_pipeline_for_date_range
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.integrations.sportmonks.client import SportmonksClient

logger = logging.getLogger(__name__)


def _run(date_str: str | None, days: int, reliability_model_type: str) -> int:
    start_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else datetime.now(timezone.utc).date()
    )

    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        with SportmonksClient(settings) as client:
            reports = run_pipeline_for_date_range(
                session,
                client,
                start_date=start_date,
                days=days,
                settings=settings,
                reliability_model_type=reliability_model_type,
            )
    finally:
        session.close()

    for report in reports:
        for step in report.steps:
            logger.info("[%s] %s %s: %s", report.ranking_date, step.status.upper(), step.name, step.detail)
        logger.info(
            "Daily pipeline for %s: %s", report.ranking_date, "all steps ok" if report.all_ok else "some steps failed"
        )

    return 0 if all(report.all_ok for report in reports) else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Daily automation pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run the full pipeline for one or more consecutive days (default: today only)"
    )
    run_parser.add_argument("--date", default=None, help="YYYY-MM-DD start date, defaults to today (UTC)")
    run_parser.add_argument(
        "--days",
        type=int,
        default=1,
        help=(
            "Run for this many consecutive days starting at --date (default: 1). "
            "E.g. --days 7 pre-populates a full week's fixtures/predictions/rankings "
            "in one run, so a real deployment doesn't need a fresh run every single "
            "day - at the cost of predictions/odds for the later days being pulled "
            "further ahead of kickoff than a same-day run would (see "
            "run_pipeline_for_date_range's docstring)."
        ),
    )
    run_parser.add_argument(
        "--reliability-model-type",
        default="final",
        help=(
            "model_type to check league eligibility against (default: final). "
            "Only model_types that have gone through 'app.ranking.cli league-reliability' "
            "have any league_model_performance rows at all - pass 'poisson' or 'ml' if "
            "'final' hasn't been backtested yet, or nothing will ever qualify."
        ),
    )

    args = parser.parse_args(argv)
    return _run(args.date, args.days, args.reliability_model_type)


if __name__ == "__main__":
    sys.exit(main())
