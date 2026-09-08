"""Builds a team's full match history as a flat list of "appearances" —
one row per fixture the team played, from that team's own perspective
(its goals/xG/stats as "for", the opponent's as "against"), regardless of
whether the team was home or away.

This "long" shape is what makes the rolling-window logic in
app/features/rolling.py simple and leakage-safe: every appearance carries
its own kickoff, so computing a team's form "as of" any timestamp is just
"filter to kickoff < cutoff, take the most recent N".

Only fixtures with a known final score (`total_goals IS NOT NULL`) are
included — an appearance with no result can't contribute to a goals-based
average, and including it would either crash or silently corrupt the mean.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, literal, select
from sqlalchemy.orm import Session, aliased

from app.db.models.fixtures import Fixture
from app.db.models.match_data import MatchStatistics, MatchXG


@dataclass(frozen=True)
class TeamAppearance:
    fixture_id: int
    opponent_id: int
    kickoff: datetime
    is_home: bool
    league_id: int
    season_id: int
    goals_for: int
    goals_against: int
    xg_for: float | None
    xg_against: float | None
    shots_for: float | None
    shots_on_target_for: float | None
    big_chances_for: float | None
    corners_for: float | None


def _side_query(team_id: int, *, home: bool):
    own_xg = aliased(MatchXG)
    opp_xg = aliased(MatchXG)
    own_stats = aliased(MatchStatistics)

    if home:
        team_col, opponent_col = Fixture.home_team_id, Fixture.away_team_id
        goals_for_col, goals_against_col = Fixture.home_goals, Fixture.away_goals
    else:
        team_col, opponent_col = Fixture.away_team_id, Fixture.home_team_id
        goals_for_col, goals_against_col = Fixture.away_goals, Fixture.home_goals

    return (
        select(
            Fixture.id.label("fixture_id"),
            opponent_col.label("opponent_id"),
            Fixture.kickoff,
            literal(home).label("is_home"),
            Fixture.league_id,
            Fixture.season_id,
            goals_for_col.label("goals_for"),
            goals_against_col.label("goals_against"),
            own_xg.xg.label("xg_for"),
            opp_xg.xg.label("xg_against"),
            own_stats.shots_total.label("shots_for"),
            own_stats.shots_on_target.label("shots_on_target_for"),
            own_stats.big_chances_created.label("big_chances_for"),
            own_stats.corners.label("corners_for"),
        )
        .select_from(Fixture)
        .outerjoin(own_xg, and_(own_xg.fixture_id == Fixture.id, own_xg.team_id == team_col))
        .outerjoin(opp_xg, and_(opp_xg.fixture_id == Fixture.id, opp_xg.team_id == opponent_col))
        .outerjoin(own_stats, and_(own_stats.fixture_id == Fixture.id, own_stats.team_id == team_col))
        .where(team_col == team_id, Fixture.total_goals.isnot(None))
    )


def fetch_team_appearances(session: Session, team_id: int) -> list[TeamAppearance]:
    """A team's entire finished-match history, unordered. Callers apply
    their own "before" cutoff and window size (see rolling.py)."""
    combined = _side_query(team_id, home=True).union_all(_side_query(team_id, home=False))
    rows = session.execute(combined).all()
    return [
        TeamAppearance(
            fixture_id=row.fixture_id,
            opponent_id=row.opponent_id,
            kickoff=row.kickoff,
            is_home=row.is_home,
            league_id=row.league_id,
            season_id=row.season_id,
            goals_for=row.goals_for,
            goals_against=row.goals_against,
            xg_for=row.xg_for,
            xg_against=row.xg_against,
            shots_for=row.shots_for,
            shots_on_target_for=row.shots_on_target_for,
            big_chances_for=row.big_chances_for,
            corners_for=row.corners_for,
        )
        for row in rows
    ]
