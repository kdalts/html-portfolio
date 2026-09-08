"""Head-to-head (matchup) features between two specific teams, using only
meetings strictly before the target fixture's kickoff, in either venue
order (team A home vs team B home both count as the same matchup).

Per spec ("Create matchup features where sufficient historical data
exists"), the rate/average fields are gated behind MIN_H2H_MATCHES —
below that, they stay None even though `h2h_matches_played` is always
reported, so a consumer can see "we found 1 meeting" rather than
confusing "no data" with "insufficient data".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models.fixtures import Fixture

MIN_H2H_MATCHES = 2


def compute_h2h_features(session: Session, *, team_a: int, team_b: int, before: datetime) -> dict[str, Any]:
    rows = session.execute(
        select(Fixture.home_goals, Fixture.away_goals, Fixture.total_goals, Fixture.over_2_5).where(
            Fixture.kickoff < before,
            Fixture.total_goals.isnot(None),
            or_(
                and_(Fixture.home_team_id == team_a, Fixture.away_team_id == team_b),
                and_(Fixture.home_team_id == team_b, Fixture.away_team_id == team_a),
            ),
        )
    ).all()

    n = len(rows)
    if n < MIN_H2H_MATCHES:
        return {
            "h2h_matches_played": n,
            "h2h_avg_total_goals": None,
            "h2h_over_2_5_pct": None,
            "h2h_btts_pct": None,
        }

    btts_count = sum(1 for r in rows if r.home_goals > 0 and r.away_goals > 0)
    return {
        "h2h_matches_played": n,
        "h2h_avg_total_goals": sum(r.total_goals for r in rows) / n,
        "h2h_over_2_5_pct": sum(1 for r in rows if r.over_2_5) / n,
        "h2h_btts_pct": btts_count / n,
    }
