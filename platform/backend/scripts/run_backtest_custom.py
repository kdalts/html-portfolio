"""One-off backtest runner for a real-data window narrower than
app/backtest/walkforward.py's default_folds() (which assumes years of
history, 2019-2025 - the spec's own illustrative example). Use this
instead when you've only ingested one season's worth of real fixtures.

Adjust TRAIN_START / TRAIN_END / TEST_END below to match what you've
actually ingested (TRAIN_END is the train/test split point - everything
before it trains the model, everything between it and TEST_END is
evaluated), then run:

    python scripts/run_backtest_custom.py
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.backtest.walkforward import WalkForwardFold, run_walkforward_backtest
from app.core.config import get_settings
from app.db.session import get_session_factory

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

TZ = timezone.utc
TRAIN_START = datetime(2025, 8, 1, tzinfo=TZ)
TRAIN_END = datetime(2026, 5, 1, tzinfo=TZ)
TEST_END = datetime(2026, 8, 1, tzinfo=TZ)
RUN_TAG = "2026season"


def main() -> None:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        fold = WalkForwardFold(TRAIN_START, TRAIN_END, TEST_END, "2026")
        run_ids = run_walkforward_backtest(session, folds=[fold], run_tag=RUN_TAG)
    finally:
        session.close()
    print("Wrote backtest_results for runs:", run_ids)


if __name__ == "__main__":
    main()
