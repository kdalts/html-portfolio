"""Small shared helpers for the prediction pipeline."""

from __future__ import annotations


def row_to_dict(row, *, exclude: frozenset[str] = frozenset()) -> dict:
    """Flatten a SQLAlchemy ORM row into a plain dict of its columns."""
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in exclude}
