"""League-level context features: what has the scoring environment in
this league/season looked like so far, using only matches strictly before
the target fixture's kickoff?

Scoped to the fixture's own season (not the league's all-time history):
scoring environments can shift year to year (rule changes, refereeing
directives, squad turnover), so blending seasons would answer a subtly
different question than "how is this league playing right now". Early in
a season this naturally means small samples — reflected honestly via
`league_sample_size` rather than gated to None, so downstream consumers
(Phase 11 ranking) can apply their own minimum-sample threshold.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.fixtures import Fixture


def compute_league_features(
    session: Session, *, league_id: int, season_id: int, before: datetime
) -> dict[str, Any]:
    rows = session.execute(
        select(Fixture.home_goals, Fixture.away_goals, Fixture.total_goals, Fixture.over_2_5).where(
            Fixture.league_id == league_id,
            Fixture.season_id == season_id,
            Fixture.kickoff < before,
            Fixture.total_goals.isnot(None),
        )
    ).all()

    n = len(rows)
    if n == 0:
        return {
            "league_avg_goals": None,
            "league_over_2_5_pct": None,
            "league_home_goals_avg": None,
            "league_away_goals_avg": None,
            "league_sample_size": 0,
        }

    return {
        "league_avg_goals": sum(r.total_goals for r in rows) / n,
        "league_over_2_5_pct": sum(1 for r in rows if r.over_2_5) / n,
        "league_home_goals_avg": sum(r.home_goals for r in rows) / n,
        "league_away_goals_avg": sum(r.away_goals for r in rows) / n,
        "league_sample_size": n,
    }
