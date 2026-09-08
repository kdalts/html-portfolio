"""Command-line entry point for the XGBoost model.

Usage:
    python -m app.models.ml_cli train --train-start 2019-08-01 --train-end 2023-08-01 --val-end 2024-08-01
    python -m app.models.ml_cli predict --start 2024-08-01 --end 2024-09-01
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
from app.models.ml_service import compute_and_store_ml_predictions, train_and_save_model

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _run_train(train_start: str, train_end: str, val_end: str) -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        result = train_and_save_model(
            session,
            train_start=_parse_date(train_start),
            train_end=_parse_date(train_end),
            val_end=_parse_date(val_end),
        )
    finally:
        session.close()

    logger.info(
        "Trained on %s rows, validated on %s rows. val_metrics=%s. Saved to %s",
        result.train_size,
        result.val_size,
        result.val_metrics,
        result.model_path,
    )
    return 0


def _run_predict(start: str, end: str) -> int:
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
        summary = compute_and_store_ml_predictions(session, list(fixtures))
    finally:
        session.close()

    logger.info(
        "ML predictions %s..%s: fetched=%s upserted=%s failed=%s",
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

    parser = argparse.ArgumentParser(description="XGBoost Over 2.5 model")
    subparsers = parser.add_subparsers(dest="command", required=True)

    train_parser = subparsers.add_parser("train", help="Train and save a model from chronologically split data")
    train_parser.add_argument("--train-start", required=True, help="YYYY-MM-DD (inclusive)")
    train_parser.add_argument("--train-end", required=True, help="YYYY-MM-DD (train/val boundary)")
    train_parser.add_argument("--val-end", required=True, help="YYYY-MM-DD (val partition ends here, exclusive)")

    predict_parser = subparsers.add_parser("predict", help="Predict for fixtures in a date range using the saved model")
    predict_parser.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    predict_parser.add_argument("--end", required=True, help="YYYY-MM-DD (exclusive)")

    args = parser.parse_args(argv)
    if args.command == "train":
        return _run_train(args.train_start, args.train_end, args.val_end)
    return _run_predict(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main())
