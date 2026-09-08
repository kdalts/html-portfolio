"""Integration tests for league- and head-to-head-level feature
computation, against a real PostgreSQL database."""

from datetime import datetime, timezone

from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.features.h2h_features import MIN_H2H_MATCHES, compute_h2h_features
from app.features.league_features import compute_league_features

UTC = timezone.utc


def _seed(session, *, n_teams=4):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    for team_id in range(1, n_teams + 1):
        session.add(Team(id=team_id, name=f"Team {team_id}"))
    session.flush()


def _add_fixture(session, fixture_id, home_id, away_id, kickoff, home_goals, away_goals, *, league_id=1, season_id=1):
    session.add(
        Fixture(
            id=fixture_id,
            league_id=league_id,
            season_id=season_id,
            kickoff=kickoff,
            home_team_id=home_id,
            away_team_id=away_id,
            home_goals=home_goals,
            away_goals=away_goals,
            status="FT",
        )
    )
    session.flush()


# --- league features -------------------------------------------------------------


def test_league_features_average_correctly(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 2, datetime(2024, 8, 1, tzinfo=UTC), 2, 1)  # total 3, over
    _add_fixture(db_session, 2, 3, 4, datetime(2024, 8, 2, tzinfo=UTC), 1, 0)  # total 1, under

    result = compute_league_features(db_session, league_id=1, season_id=1, before=datetime(2024, 8, 10, tzinfo=UTC))
    assert result["league_sample_size"] == 2
    assert result["league_avg_goals"] == 2.0  # (3+1)/2
    assert result["league_over_2_5_pct"] == 0.5
    assert result["league_home_goals_avg"] == 1.5  # (2+1)/2
    assert result["league_away_goals_avg"] == 0.5  # (1+0)/2


def test_league_features_exclude_matches_on_or_after_cutoff(db_session):
    _seed(db_session)
    cutoff = datetime(2024, 8, 10, tzinfo=UTC)
    _add_fixture(db_session, 1, 1, 2, datetime(2024, 8, 1, tzinfo=UTC), 2, 1)
    _add_fixture(db_session, 2, 3, 4, cutoff, 5, 5)  # exactly at cutoff - excluded

    result = compute_league_features(db_session, league_id=1, season_id=1, before=cutoff)
    assert result["league_sample_size"] == 1
    assert result["league_avg_goals"] == 3.0


def test_league_features_scoped_to_season(db_session):
    _seed(db_session)
    db_session.add(Season(id=2, league_id=1, name="2023/2024"))
    db_session.flush()
    _add_fixture(db_session, 1, 1, 2, datetime(2023, 8, 1, tzinfo=UTC), 9, 9, season_id=2)  # different season
    _add_fixture(db_session, 2, 3, 4, datetime(2024, 8, 1, tzinfo=UTC), 1, 1)

    result = compute_league_features(db_session, league_id=1, season_id=1, before=datetime(2024, 9, 1, tzinfo=UTC))
    assert result["league_sample_size"] == 1
    assert result["league_avg_goals"] == 2.0


def test_league_features_empty_returns_none(db_session):
    _seed(db_session)
    result = compute_league_features(db_session, league_id=1, season_id=1, before=datetime(2024, 8, 1, tzinfo=UTC))
    assert result["league_sample_size"] == 0
    assert result["league_avg_goals"] is None


# --- head-to-head features ---------------------------------------------------------


def test_h2h_below_threshold_returns_none_fields_but_reports_count(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 2, datetime(2024, 8, 1, tzinfo=UTC), 2, 1)
    assert MIN_H2H_MATCHES >= 2

    result = compute_h2h_features(db_session, team_a=1, team_b=2, before=datetime(2024, 9, 1, tzinfo=UTC))
    assert result["h2h_matches_played"] == 1
    assert result["h2h_avg_total_goals"] is None
    assert result["h2h_over_2_5_pct"] is None


def test_h2h_at_threshold_counts_both_venue_orders(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 2, datetime(2023, 8, 1, tzinfo=UTC), 2, 1)  # team1 home
    _add_fixture(db_session, 2, 2, 1, datetime(2024, 1, 1, tzinfo=UTC), 0, 0)  # team2 home (reversed)

    result = compute_h2h_features(db_session, team_a=1, team_b=2, before=datetime(2024, 9, 1, tzinfo=UTC))
    assert result["h2h_matches_played"] == 2
    assert result["h2h_avg_total_goals"] == 1.5  # (3+0)/2
    assert result["h2h_over_2_5_pct"] == 0.5
    assert result["h2h_btts_pct"] == 0.5  # only the first was btts


def test_h2h_unrelated_matches_do_not_count(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 3, datetime(2024, 8, 1, tzinfo=UTC), 5, 5)  # team1 vs team3, irrelevant
    _add_fixture(db_session, 2, 2, 4, datetime(2024, 8, 2, tzinfo=UTC), 5, 5)  # team2 vs team4, irrelevant

    result = compute_h2h_features(db_session, team_a=1, team_b=2, before=datetime(2024, 9, 1, tzinfo=UTC))
    assert result["h2h_matches_played"] == 0


def test_h2h_excludes_matches_on_or_after_cutoff(db_session):
    _seed(db_session)
    cutoff = datetime(2024, 8, 10, tzinfo=UTC)
    _add_fixture(db_session, 1, 1, 2, datetime(2024, 8, 1, tzinfo=UTC), 2, 1)
    _add_fixture(db_session, 2, 1, 2, cutoff, 9, 9)  # exactly at cutoff

    result = compute_h2h_features(db_session, team_a=1, team_b=2, before=cutoff)
    assert result["h2h_matches_played"] == 1
