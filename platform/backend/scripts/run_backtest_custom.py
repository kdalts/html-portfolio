"""One-off backtest runner for a real-data window narrower than
app/backtest/walkforward.py's default_folds() (which assumes years of
history, 2019-2025 - the spec's own illustrative example). Use this
instead when you've only ingested one/two seasons of real fixtures.

FOLDS below defines a genuine expanding-window walk-forward: each fold's
train_start stays fixed at the start of your ingested history, train_end
grows fold to fold, and each fold tests on the period right after its
own training window (never overlapping an earlier fold's test period).
Adjust to match what you've actually ingested, then run:

    python scripts/run_backtest_custom.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run as a plain script (not `python -m ...`), so the `app` package
# (one directory up, in backend/) isn't on sys.path by default - add it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtest.walkforward import WalkForwardFold, run_walkforward_backtest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

TZ = timezone.utc
HISTORY_START = datetime(2024, 8, 1, tzinfo=TZ)
FOLDS = [
    WalkForwardFold(HISTORY_START, datetime(2025, 8, 1, tzinfo=TZ), datetime(2026, 2, 1, tzinfo=TZ), "2025H2"),
    WalkForwardFold(HISTORY_START, datetime(2026, 2, 1, tzinfo=TZ), datetime(2026, 8, 1, tzinfo=TZ), "2026H1"),
]
RUN_TAG = "2yr"


def main() -> None:
    settings = get_settings()
    session = get_session_factory(settings)()
    try:
        run_ids = run_walkforward_backtest(session, folds=FOLDS, run_tag=RUN_TAG)
    finally:
        session.close()
    print("Wrote backtest_results for runs:", run_ids)


if __name__ == "__main__":
    main()
