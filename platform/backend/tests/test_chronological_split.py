"""Pure unit tests for chronological_split - no database, no ML."""

from datetime import datetime, timezone

import pandas as pd

from app.models.chronological_split import chronological_split

UTC = timezone.utc


def _df(dates: list[datetime]) -> pd.DataFrame:
    return pd.DataFrame({"kickoff": dates, "value": list(range(len(dates)))})


def test_splits_by_kickoff_cutoffs():
    df = _df(
        [
            datetime(2019, 1, 1, tzinfo=UTC),
            datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2021, 1, 1, tzinfo=UTC),
            datetime(2022, 1, 1, tzinfo=UTC),
        ]
    )
    train, val, test = chronological_split(
        df, train_end=datetime(2021, 1, 1, tzinfo=UTC), val_end=datetime(2022, 1, 1, tzinfo=UTC)
    )
    assert list(train["value"]) == [0, 1]  # 2019, 2020
    assert list(val["value"]) == [2]  # 2021 (train_end <= x < val_end)
    assert list(test["value"]) == [3]  # 2022 (>= val_end)


def test_no_overlap_and_no_gaps():
    df = _df([datetime(2019 + i, 1, 1, tzinfo=UTC) for i in range(10)])
    train, val, test = chronological_split(
        df, train_end=datetime(2024, 1, 1, tzinfo=UTC), val_end=datetime(2027, 1, 1, tzinfo=UTC)
    )
    assert len(train) + len(val) + len(test) == len(df)
    assert set(train["value"]) & set(val["value"]) == set()
    assert set(val["value"]) & set(test["value"]) == set()


def test_never_shuffles_rows_within_a_partition():
    """Rows are supplied out of chronological order; the split must sort
    them, never leave them scrambled or introduce randomness."""
    dates = [datetime(2020, 6, 1, tzinfo=UTC), datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 3, 1, tzinfo=UTC)]
    df = _df(dates)
    train, _val, _test = chronological_split(
        df, train_end=datetime(2021, 1, 1, tzinfo=UTC), val_end=datetime(2022, 1, 1, tzinfo=UTC)
    )
    assert list(train["kickoff"]) == sorted(dates)


def test_empty_validation_window_is_allowed():
    df = _df([datetime(2019, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)])
    train, val, test = chronological_split(
        df, train_end=datetime(2020, 1, 1, tzinfo=UTC), val_end=datetime(2020, 1, 2, tzinfo=UTC)
    )
    assert len(train) == 1
    assert len(val) == 0
    assert len(test) == 1


def test_boundary_dates_are_exclusive_on_the_upper_side():
    """A row exactly at train_end belongs to val, not train; a row
    exactly at val_end belongs to test, not val."""
    cutoff = datetime(2021, 1, 1, tzinfo=UTC)
    df = _df([cutoff])
    train, val, _test = chronological_split(df, train_end=cutoff, val_end=cutoff + pd.Timedelta(days=1))
    assert len(train) == 0
    assert len(val) == 1
