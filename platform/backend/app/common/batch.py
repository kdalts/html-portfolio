"""A generic per-item batch-processing result, shared by every pipeline
that processes many independent records and must not let one bad record
abort the rest (ingestion, feature computation, ...)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BatchSummary:
    fetched: int = 0
    upserted: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def record_error(self, identifier: object, exc: Exception) -> None:
        self.failed += 1
        self.errors.append(f"{identifier}: {exc}")

    def __bool__(self) -> bool:
        """A summary is "successful" if nothing failed."""
        return self.failed == 0
