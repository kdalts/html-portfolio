"""Chronological (never random) train/validation/test splitting.

Per spec: "Use chronological train/validation/test splits. Never randomly
shuffle historical matches across time." This filters by kickoff cutoff,
which by construction preserves time order and cannot leak a later match
into an earlier partition - there is no shuffling step to get wrong.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def chronological_split(
    df: pd.DataFrame,
    *,
    train_end: datetime,
    val_end: datetime,
    date_column: str = "kickoff",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """train: kickoff < train_end
    val:   train_end <= kickoff < val_end
    test:  kickoff >= val_end
    """
    train = df[df[date_column] < train_end].sort_values(date_column).reset_index(drop=True)
    val = df[(df[date_column] >= train_end) & (df[date_column] < val_end)].sort_values(date_column).reset_index(
        drop=True
    )
    test = df[df[date_column] >= val_end].sort_values(date_column).reset_index(drop=True)
    return train, val, test
