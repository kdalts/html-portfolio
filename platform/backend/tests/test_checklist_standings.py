"""Real-PostgreSQL tests for computing a league table purely from stored
fixture results: correct points/goal-difference ordering, and that a
match at or after the cutoff never affects the standings (leakage
boundary, same discipline as every other feature in this codebase)."""

from datetime import datetime, timedelta, timezone

from app.checklist.standings import compute_league_standings
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team

UTC = timezone.utc
BASE = datetime(2024, 8, 1, tzinfo=UTC)


def _seed_teams(session, n=3):
    session.add(League(id=1, name="Test League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    for i in range(1, n + 1):
        session.add(Team(id=i, name=f"Team {i}"))
    session.flush()


def test_standings_ranks_by_points_then_goal_difference(db_session):
    _seed_teams(db_session, 3)
    # Team 1 beats Team 2 3-0, Team 2 beats Team 3 1-0, Team 1 draws Team 3 1-1
    db_session.add_all(
        [
            Fixture(
                id=1, league_id=1, season_id=1, kickoff=BASE, home_team_id=1, away_team_id=2,
                home_goals=3, away_goals=0, status="FT",
            ),
            Fixture(
                id=2, league_id=1, season_id=1, kickoff=BASE + timedelta(days=1), home_team_id=2, away_team_id=3,
                home_goals=1, away_goals=0, status="FT",
            ),
            Fixture(
                id=3, league_id=1, season_id=1, kickoff=BASE + timedelta(days=2), home_team_id=1, away_team_id=3,
                home_goals=1, away_goals=1, status="FT",
            ),
        ]
    )
    db_session.flush()

    standings = compute_league_standings(
        db_session, league_id=1, season_id=1, before=BASE + timedelta(days=3)
    )

    # Team 1: 3+1=4 pts, GF 4 GA 1, GD +3
    # Team 2: 3+0=3 pts, GF 1 GA 4, GD -3
    # Team 3: 0+1=1 pt,  GF 1 GA 2, GD -1
    assert standings[1].points == 4
    assert standings[1].position == 1
    assert standings[2].points == 3
    assert standings[2].position == 2
    assert standings[3].points == 1
    assert standings[3].position == 3
    assert standings[1].goal_difference == 3


def test_standings_never_include_a_match_at_or_after_the_cutoff(db_session):
    _seed_teams(db_session, 2)
    db_session.add(
        Fixture(
            id=1, league_id=1, season_id=1, kickoff=BASE, home_team_id=1, away_team_id=2,
            home_goals=5, away_goals=0, status="FT",
        )
    )
    db_session.flush()

    # exactly at the match's own kickoff - must be excluded (strict <)
    standings_at_kickoff = compute_league_standings(db_session, league_id=1, season_id=1, before=BASE)
    assert standings_at_kickoff == {}

    # a moment after - now it counts
    standings_after = compute_league_standings(
        db_session, league_id=1, season_id=1, before=BASE + timedelta(seconds=1)
    )
    assert standings_after[1].points == 3


def test_standings_omits_teams_with_no_qualifying_matches(db_session):
    _seed_teams(db_session, 3)
    db_session.add(
        Fixture(
            id=1, league_id=1, season_id=1, kickoff=BASE, home_team_id=1, away_team_id=2,
            home_goals=1, away_goals=1, status="FT",
        )
    )
    db_session.flush()

    standings = compute_league_standings(db_session, league_id=1, season_id=1, before=BASE + timedelta(days=1))
    assert 1 in standings
    assert 2 in standings
    assert 3 not in standings
