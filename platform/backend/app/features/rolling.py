"""Pure rolling-window feature computation over a team's appearance
history. No database access — everything here operates on plain
TeamAppearance objects, which is what makes it fast and exhaustively
testable without a live Postgres instance.

The leakage boundary is enforced right here, once, for every caller:
`compute_rolling_stats` only ever considers appearances with
`kickoff < before` (strictly before — an appearance exactly at `before`
is excluded). Since a fixture's own kickoff is never strictly less than
itself, computing a fixture's features with `before=fixture.kickoff` can
never include that fixture's own result, even if it has already been
played (which is exactly the case backtesting relies on).

Column names produced here are generated from the same STAT_KEYS /
ROLLING_WINDOWS / FEATURE_CONTEXTS constants the team_features table
schema uses (app/db/models/features.py), so the two can never drift apart.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.db.models.features import FEATURE_CONTEXTS, ROLLING_WINDOWS, STAT_KEYS
from app.features.team_match_log import TeamAppearance


def _btts_flag(appearance: TeamAppearance) -> float | None:
    if appearance.goals_for is None or appearance.goals_against is None:
        return None
    return 1.0 if (appearance.goals_for > 0 and appearance.goals_against > 0) else 0.0


def _over_2_5_flag(appearance: TeamAppearance) -> float | None:
    if appearance.goals_for is None or appearance.goals_against is None:
        return None
    return 1.0 if (appearance.goals_for + appearance.goals_against) >= 3 else 0.0


# stat name -> accessor extracting that stat's value from one appearance.
# Every key in STAT_KEYS must have exactly one accessor here; enforced by
# the assertion below at import time, so a typo can't silently drop a stat.
_STAT_ACCESSORS: dict[str, Callable[[TeamAppearance], float | None]] = {
    "goals_scored": lambda a: a.goals_for,
    "goals_conceded": lambda a: a.goals_against,
    "xg": lambda a: a.xg_for,
    "xga": lambda a: a.xg_against,
    "shots": lambda a: a.shots_for,
    "shots_on_target": lambda a: a.shots_on_target_for,
    "big_chances": lambda a: a.big_chances_for,
    "corners": lambda a: a.corners_for,
    "btts_pct": _btts_flag,
    "over_2_5_pct": _over_2_5_flag,
}

assert set(_STAT_ACCESSORS) == set(STAT_KEYS), "rolling.py stat accessors have drifted from STAT_KEYS"


def _average(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return (sum(present) / len(present)) if present else None


def compute_rolling_stats(
    appearances: list[TeamAppearance], *, before: datetime, window: int
) -> dict[str, float | int | None]:
    """The team's form over its most recent `window` appearances strictly
    before `before`. Returns {"matches_played": n, **{stat: value|None}}.
    A stat is None if there were zero prior matches, or every match in
    the window has a missing value for that specific stat."""
    prior = [a for a in appearances if a.kickoff < before]
    prior.sort(key=lambda a: a.kickoff, reverse=True)
    window_apps = prior[:window]

    result: dict[str, float | int | None] = {"matches_played": len(window_apps)}
    for stat_name, accessor in _STAT_ACCESSORS.items():
        result[stat_name] = _average([accessor(a) for a in window_apps])
    return result


def compute_team_rolling_features(
    all_appearances: list[TeamAppearance], *, before: datetime, target_is_home: bool
) -> dict[str, Any]:
    """The full team_features row (minus id/team_id/fixture_id/metadata)
    for a team entering a fixture where it plays as home (target_is_home)
    or away. "overall" uses the team's whole history; "venue" restricts to
    appearances in the same venue role as the target fixture."""
    venue_appearances = [a for a in all_appearances if a.is_home == target_is_home]
    contexts = {"overall": all_appearances, "venue": venue_appearances}
    assert set(contexts) == set(FEATURE_CONTEXTS)

    result: dict[str, Any] = {}
    for context, appearances in contexts.items():
        for window in ROLLING_WINDOWS:
            stats = compute_rolling_stats(appearances, before=before, window=window)
            result[f"{context}_last{window}_matches_played"] = stats["matches_played"]
            for stat_name in STAT_KEYS:
                result[f"{context}_last{window}_{stat_name}"] = stats[stat_name]
    return result
