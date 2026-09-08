"""Generic idempotent upsert (INSERT ... ON CONFLICT DO UPDATE), shared by
every module that writes to the database (ingestion, feature computation).
Re-running a write over the same key always updates in place; it never
duplicates.

Generated columns (fixtures.total_goals/over_2_5, odds' implied
probabilities/market_probability, model_predictions.edge) must never be
part of the `values` dict — Postgres computes them, and the database
rejects an attempt to set them explicitly.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session


def upsert_one(session: Session, model, values: dict[str, Any], conflict_columns: list[str]) -> Any:
    table = model.__table__
    stmt = pg_insert(table).values(**values)
    settable = {name: stmt.excluded[name] for name in values if name not in conflict_columns}
    settable["updated_at"] = func.now()
    stmt = stmt.on_conflict_do_update(index_elements=conflict_columns, set_=settable)
    pk_columns = [c.name for c in table.primary_key.columns]
    stmt = stmt.returning(*[table.c[name] for name in pk_columns])
    result = session.execute(stmt).one()
    return result[0] if len(pk_columns) == 1 else tuple(result)
