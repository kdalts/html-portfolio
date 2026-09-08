"""Command-line entry point for walk-forward backtesting.

Usage:
    python -m app.backtest.cli run [--model-types poisson,ml] [--run-tag mytag]
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.backtest.walkforward import SUPPORTED_MODEL_TYPES, run_walkforward_backtest

logger = logging.getLogger(__name__)


def _run(model_types: list[str], run_tag: str | None) -> int:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        run_ids = run_walkforward_backtest(session, model_types=tuple(model_types), run_tag=run_tag)
    finally:
        session.close()

    logger.info("Wrote backtest_results for runs: %s", run_ids)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Walk-forward backtesting")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the default expanding-window walk-forward backtest")
    run_parser.add_argument(
        "--model-types",
        default=",".join(SUPPORTED_MODEL_TYPES),
        help=f"Comma-separated subset of {SUPPORTED_MODEL_TYPES}",
    )
    run_parser.add_argument("--run-tag", default=None, help="Groups this run's per-fold backtest_run_ids")

    args = parser.parse_args(argv)
    model_types = [m.strip() for m in args.model_types.split(",") if m.strip()]
    return _run(model_types, args.run_tag)


if __name__ == "__main__":
    sys.exit(main())
