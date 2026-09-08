"""Command-line entry point for the ranking engine.

Usage:
    python -m app.ranking.cli league-reliability --run-ids wf-2026-2023,wf-2026-2024 --model-type poisson \
        --window-start 2019-01-01 --window-end 2025-01-01
    python -m app.ranking.cli daily --date 2024-08-17 [--reliability-model-type poisson]
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.ranking.daily_ranking_service import DEFAULT_TOP_N, build_daily_ranking
from app.ranking.league_reliability_service import compute_and_store_league_reliability

logger = logging.getLogger(__name__)


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).date()


def _run_league_reliability(run_ids: list[str], model_type: str, window_start: str, window_end: str) -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        summary = compute_and_store_league_reliability(
            session,
            backtest_run_ids=run_ids,
            model_type=model_type,
            evaluation_window_start=_parse_date(window_start),
            evaluation_window_end=_parse_date(window_end),
        )
    finally:
        session.close()

    logger.info("League reliability: fetched=%s upserted=%s failed=%s", summary.fetched, summary.upserted, summary.failed)
    for error in summary.errors:
        logger.warning(error)
    return 0 if summary else 1


def _run_daily(ranking_date: str, reliability_model_type: str) -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        result = build_daily_ranking(
            session, ranking_date=_parse_date(ranking_date), reliability_model_type=reliability_model_type
        )
    finally:
        session.close()

    logger.info(
        "Daily ranking %s: considered=%s qualified=%s ranked=%s",
        ranking_date,
        result["considered"],
        result["qualified"],
        result["ranked"],
    )
    for fixture_id, reason in result["excluded"].items():
        logger.info("  excluded fixture %s: %s", fixture_id, reason)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Ranking engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    reliability_parser = subparsers.add_parser("league-reliability", help="Compute league_model_performance from backtest_results")
    reliability_parser.add_argument("--run-ids", required=True, help="Comma-separated backtest_run_ids")
    reliability_parser.add_argument("--model-type", required=True)
    reliability_parser.add_argument("--window-start", required=True, help="YYYY-MM-DD")
    reliability_parser.add_argument("--window-end", required=True, help="YYYY-MM-DD")

    daily_parser = subparsers.add_parser("daily", help=f"Build the daily Top {DEFAULT_TOP_N} for a date")
    daily_parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    daily_parser.add_argument("--reliability-model-type", default="final")

    args = parser.parse_args(argv)
    if args.command == "league-reliability":
        run_ids = [r.strip() for r in args.run_ids.split(",") if r.strip()]
        return _run_league_reliability(run_ids, args.model_type, args.window_start, args.window_end)
    return _run_daily(args.date, args.reliability_model_type)


if __name__ == "__main__":
    sys.exit(main())
