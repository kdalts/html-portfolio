"""Computes a league table (points, goal difference, position) purely
from stored fixture results — no separate standings ingestion needed,
since every finished match's score is already in the database.

Same leakage discipline as every other feature in this codebase: only
matches strictly before `before` are counted, so a standings snapshot for
a given fixture can never include information from matches that hadn't
been played yet at that point.

Standard 3-1-0 points, ties broken by goal difference then goals scored —
the conventional football league-table ordering. A team that hasn't
played any qualifying match in this league/season simply doesn't appear
in the result; callers must treat a missing team_id as "no position
available", not position 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.fixtures import Fixture


@dataclass(frozen=True)
class StandingsRow:
    team_id: int
    played: int
    points: int
    goals_for: int
    goals_against: int
    goal_difference: int
    position: int  # 1 = top of the table


def compute_league_standings(
    session: Session, *, league_id: int, season_id: int, before: datetime
) -> dict[int, StandingsRow]:
    rows = session.execute(
        select(Fixture.home_team_id, Fixture.away_team_id, Fixture.home_goals, Fixture.away_goals).where(
            Fixture.league_id == league_id,
            Fixture.season_id == season_id,
            Fixture.kickoff < before,
            Fixture.total_goals.isnot(None),
        )
    ).all()

    stats: dict[int, dict[str, int]] = {}

    def _team(team_id: int) -> dict[str, int]:
        return stats.setdefault(team_id, {"played": 0, "points": 0, "goals_for": 0, "goals_against": 0})

    for home_id, away_id, home_goals, away_goals in rows:
        home, away = _team(home_id), _team(away_id)
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += home_goals
        home["goals_against"] += away_goals
        away["goals_for"] += away_goals
        away["goals_against"] += home_goals
        if home_goals > away_goals:
            home["points"] += 3
        elif away_goals > home_goals:
            away["points"] += 3
        else:
            home["points"] += 1
            away["points"] += 1

    ordered = sorted(
        stats.items(),
        key=lambda item: (
            -item[1]["points"],
            -(item[1]["goals_for"] - item[1]["goals_against"]),
            -item[1]["goals_for"],
        ),
    )

    return {
        team_id: StandingsRow(
            team_id=team_id,
            played=s["played"],
            points=s["points"],
            goals_for=s["goals_for"],
            goals_against=s["goals_against"],
            goal_difference=s["goals_for"] - s["goals_against"],
            position=position,
        )
        for position, (team_id, s) in enumerate(ordered, start=1)
    }
