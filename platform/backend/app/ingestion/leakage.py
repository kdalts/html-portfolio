"""The leakage guard: the one function every timestamped, pre-match piece
of data (Sportmonks predictions, odds) must pass through before it is
stored. This is the system-wide enforcement point for the platform's core
rule: never use information that was unavailable at the prediction
timestamp.

Deliberately strict: `observed_at` must be *strictly* before `kickoff`
(not <=), and both timestamps must be timezone-aware, so an accidental
naive-datetime comparison can never silently pass.
"""

from datetime import datetime

from app.ingestion.errors import LeakageError


def ensure_not_leaked(observed_at: datetime, kickoff: datetime, *, label: str) -> None:
    if observed_at is None or kickoff is None:
        raise LeakageError(f"{label}: cannot verify timing without both a kickoff and an observed timestamp")
    if observed_at.tzinfo is None or kickoff.tzinfo is None:
        raise LeakageError(f"{label}: timestamps must be timezone-aware to compare safely")
    if observed_at >= kickoff:
        raise LeakageError(
            f"{label} was observed at {observed_at.isoformat()}, which is not strictly before "
            f"kickoff at {kickoff.isoformat()}. Refusing to store data that could leak "
            "post-kickoff information into a pre-match feature or prediction."
        )
