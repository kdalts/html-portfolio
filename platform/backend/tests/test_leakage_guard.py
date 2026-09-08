from datetime import datetime, timezone

import pytest

from app.ingestion.errors import LeakageError
from app.ingestion.leakage import ensure_not_leaked

KICKOFF = datetime(2024, 8, 17, 15, 0, tzinfo=timezone.utc)


def test_observed_strictly_before_kickoff_is_allowed():
    observed = datetime(2024, 8, 17, 12, 0, tzinfo=timezone.utc)
    ensure_not_leaked(observed, KICKOFF, label="test")  # must not raise


def test_observed_at_exact_kickoff_is_rejected():
    with pytest.raises(LeakageError):
        ensure_not_leaked(KICKOFF, KICKOFF, label="test")


def test_observed_after_kickoff_is_rejected():
    observed = datetime(2024, 8, 17, 15, 0, 1, tzinfo=timezone.utc)
    with pytest.raises(LeakageError):
        ensure_not_leaked(observed, KICKOFF, label="test")


def test_observed_long_after_kickoff_is_rejected():
    """The realistic historical-backfill failure mode: pulling
    'predictions' for a match that finished months ago."""
    observed = datetime(2024, 12, 1, tzinfo=timezone.utc)
    with pytest.raises(LeakageError):
        ensure_not_leaked(observed, KICKOFF, label="test")


def test_naive_observed_datetime_is_rejected():
    naive = datetime(2024, 8, 17, 12, 0)  # no tzinfo
    with pytest.raises(LeakageError):
        ensure_not_leaked(naive, KICKOFF, label="test")


def test_naive_kickoff_is_rejected():
    naive_kickoff = datetime(2024, 8, 17, 15, 0)
    observed = datetime(2024, 8, 17, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(LeakageError):
        ensure_not_leaked(observed, naive_kickoff, label="test")


def test_missing_timestamps_are_rejected():
    with pytest.raises(LeakageError):
        ensure_not_leaked(None, KICKOFF, label="test")
    with pytest.raises(LeakageError):
        ensure_not_leaked(datetime.now(timezone.utc), None, label="test")


def test_error_message_includes_label_and_both_timestamps():
    observed = datetime(2024, 12, 1, tzinfo=timezone.utc)
    with pytest.raises(LeakageError) as exc_info:
        ensure_not_leaked(observed, KICKOFF, label="odds.retrieved_at")
    message = str(exc_info.value)
    assert "odds.retrieved_at" in message
    assert observed.isoformat() in message
    assert KICKOFF.isoformat() in message
