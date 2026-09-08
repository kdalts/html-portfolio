"""Command-line entry point for ensemble weighting + calibration.

Usage:
    python -m app.models.ensemble_cli fit --val-start 2023-08-01 --val-end 2024-08-01
    python -m app.models.ensemble_cli apply --start 2024-08-01 --end 2024-09-01
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
from app.models.ensemble_service import apply_ensemble_and_calibration_for_fixtures, fit_ensemble_and_calibration

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _run_fit(val_start: str, val_end: str) -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        result = fit_ensemble_and_calibration(session, val_start=_parse_date(val_start), val_end=_parse_date(val_end))
    finally:
        session.close()

    logger.info(
        "Fitted on %s validation rows. weights=%s calibration=%s. Saved to %s",
        result.val_size,
        result.ensemble_weights,
        result.calibration_method,
        result.artifact_path,
    )
    return 0


def _run_apply(start: str, end: str) -> int:
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
        summary = apply_ensemble_and_calibration_for_fixtures(session, list(fixtures))
    finally:
        session.close()

    logger.info(
        "Ensemble/calibration %s..%s: fetched=%s upserted=%s failed=%s",
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

    parser = argparse.ArgumentParser(description="Ensemble weighting + probability calibration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fit_parser = subparsers.add_parser("fit", help="Fit ensemble weights and select a calibration method")
    fit_parser.add_argument("--val-start", required=True, help="YYYY-MM-DD (inclusive)")
    fit_parser.add_argument("--val-end", required=True, help="YYYY-MM-DD (exclusive)")

    apply_parser = subparsers.add_parser("apply", help="Compute final_probability for fixtures in a date range")
    apply_parser.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    apply_parser.add_argument("--end", required=True, help="YYYY-MM-DD (exclusive)")

    args = parser.parse_args(argv)
    if args.command == "fit":
        return _run_fit(args.val_start, args.val_end)
    return _run_apply(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main())
