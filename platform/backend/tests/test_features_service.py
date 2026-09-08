"""Integration tests for the feature computation service, against a real
PostgreSQL database."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.db.models.match_data import MatchStatistics, MatchXG
from app.features.service import compute_and_store_features_for_fixtures, compute_features_for_fixture
from app.features.team_match_log import fetch_team_appearances

UTC = timezone.utc


def _seed(session, *, n_teams=4):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    for team_id in range(1, n_teams + 1):
        session.add(Team(id=team_id, name=f"Team {team_id}"))
    session.flush()


def _add_fixture(session, fixture_id, home_id, away_id, kickoff, home_goals=None, away_goals=None, status="NS"):
    session.add(
        Fixture(
            id=fixture_id,
            league_id=1,
            season_id=1,
            kickoff=kickoff,
            home_team_id=home_id,
            away_team_id=away_id,
            home_goals=home_goals,
            away_goals=away_goals,
            status=status,
        )
    )
    session.flush()
    return session.get(Fixture, fixture_id)


# --- team_match_log ----------------------------------------------------------------


def test_fetch_team_appearances_covers_home_and_away(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 2, datetime(2024, 8, 1, tzinfo=UTC), 2, 1, status="FT")
    _add_fixture(db_session, 2, 3, 1, datetime(2024, 8, 8, tzinfo=UTC), 0, 4, status="FT")

    appearances = fetch_team_appearances(db_session, 1)
    assert len(appearances) == 2
    by_fixture = {a.fixture_id: a for a in appearances}

    assert by_fixture[1].is_home is True
    assert by_fixture[1].goals_for == 2
    assert by_fixture[1].goals_against == 1

    assert by_fixture[2].is_home is False
    assert by_fixture[2].goals_for == 4  # team 1 is away, scored 4
    assert by_fixture[2].goals_against == 0


def test_fetch_team_appearances_pulls_xg_from_own_and_opponent_rows(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 2, datetime(2024, 8, 1, tzinfo=UTC), 2, 1, status="FT")
    db_session.add(MatchXG(fixture_id=1, team_id=1, xg=1.8))
    db_session.add(MatchXG(fixture_id=1, team_id=2, xg=0.9))
    db_session.add(MatchStatistics(fixture_id=1, team_id=1, shots_total=15, corners=6))
    db_session.flush()

    appearances = fetch_team_appearances(db_session, 1)
    assert len(appearances) == 1
    a = appearances[0]
    assert a.xg_for == 1.8
    assert a.xg_against == 0.9  # opponent's own xg row
    assert a.shots_for == 15
    assert a.corners_for == 6


def test_fetch_team_appearances_excludes_matches_without_a_result(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 2, datetime(2024, 8, 1, tzinfo=UTC), status="NS")  # no goals yet
    appearances = fetch_team_appearances(db_session, 1)
    assert appearances == []


# --- compute_features_for_fixture: the critical leakage guarantee ------------------


def test_a_fixtures_own_result_never_leaks_into_its_own_features(db_session):
    """The single most important test in this phase: even though fixture 4
    has already been played (status=FT, goals recorded), computing its
    features must use ONLY fixtures 1-3 - never its own score."""
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 3, datetime(2024, 8, 1, tzinfo=UTC), 1, 0, status="FT")
    _add_fixture(db_session, 2, 1, 4, datetime(2024, 8, 8, tzinfo=UTC), 2, 0, status="FT")
    _add_fixture(db_session, 3, 1, 3, datetime(2024, 8, 15, tzinfo=UTC), 3, 0, status="FT")
    target = _add_fixture(db_session, 4, 1, 2, datetime(2024, 8, 22, tzinfo=UTC), 99, 99, status="FT")

    home_values, away_values, match_values = compute_features_for_fixture(db_session, target)

    # team 1's rolling goals_scored must be the mean of [1, 2, 3] = 2.0,
    # NOT influenced by the 99 recorded on the target fixture itself.
    assert home_values["overall_last3_matches_played"] == 3
    assert home_values["overall_last3_goals_scored"] == 2.0
    assert home_values["overall_last10_goals_scored"] == 2.0


def test_upcoming_unplayed_fixture_still_gets_features_from_prior_history(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 3, datetime(2024, 8, 1, tzinfo=UTC), 2, 0, status="FT")
    upcoming = _add_fixture(db_session, 2, 1, 2, datetime(2024, 8, 30, tzinfo=UTC), status="NS")

    home_values, _, _ = compute_features_for_fixture(db_session, upcoming)
    assert home_values["overall_last10_matches_played"] == 1
    assert home_values["overall_last10_goals_scored"] == 2.0


def test_match_features_include_league_and_h2h(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 3, 4, datetime(2024, 8, 1, tzinfo=UTC), 1, 1, status="FT")
    _add_fixture(db_session, 2, 1, 2, datetime(2023, 1, 1, tzinfo=UTC), 2, 2, status="FT")  # h2h #1
    _add_fixture(db_session, 3, 2, 1, datetime(2023, 6, 1, tzinfo=UTC), 0, 1, status="FT")  # h2h #2
    target = _add_fixture(db_session, 4, 1, 2, datetime(2024, 8, 10, tzinfo=UTC), status="NS")

    _, _, match_values = compute_features_for_fixture(db_session, target)
    # all three prior fixtures (1, 2, 3) share league_id=1/season_id=1
    assert match_values["league_sample_size"] == 3
    assert match_values["h2h_matches_played"] == 2
    assert match_values["h2h_avg_total_goals"] == 2.5  # (4+1)/2
    assert 0.0 <= match_values["data_completeness_score"] <= 1.0


# --- batch driver: storage + idempotency + error isolation -------------------------


def test_compute_and_store_features_persists_rows(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 3, datetime(2024, 8, 1, tzinfo=UTC), 2, 0, status="FT")
    target = _add_fixture(db_session, 2, 1, 2, datetime(2024, 8, 10, tzinfo=UTC), status="NS")

    summary = compute_and_store_features_for_fixtures(db_session, [target], commit=False)
    db_session.flush()

    assert summary.fetched == 1
    assert summary.upserted == 1
    assert summary.failed == 0

    team_rows = db_session.execute(select(TeamFeatures).where(TeamFeatures.fixture_id == 2)).scalars().all()
    assert {r.team_id for r in team_rows} == {1, 2}
    match_row = db_session.execute(select(MatchFeatures).where(MatchFeatures.fixture_id == 2)).scalar_one()
    assert match_row.fixture_id == 2


def test_compute_and_store_features_is_idempotent(db_session):
    _seed(db_session)
    _add_fixture(db_session, 1, 1, 3, datetime(2024, 8, 1, tzinfo=UTC), 2, 0, status="FT")
    target = _add_fixture(db_session, 2, 1, 2, datetime(2024, 8, 10, tzinfo=UTC), status="NS")

    compute_and_store_features_for_fixtures(db_session, [target], commit=False)
    db_session.flush()
    compute_and_store_features_for_fixtures(db_session, [target], commit=False)
    db_session.flush()

    team_rows = db_session.execute(select(TeamFeatures).where(TeamFeatures.fixture_id == 2)).scalars().all()
    assert len(team_rows) == 2  # one per team, still not duplicated per team


def test_one_bad_fixture_does_not_abort_the_batch(db_session):
    _seed(db_session, n_teams=4)
    _add_fixture(db_session, 1, 1, 3, datetime(2024, 8, 1, tzinfo=UTC), 2, 0, status="FT")
    good_a = _add_fixture(db_session, 2, 1, 2, datetime(2024, 8, 10, tzinfo=UTC), status="NS")
    good_b = _add_fixture(db_session, 3, 3, 4, datetime(2024, 8, 11, tzinfo=UTC), status="NS")

    # a fixture referencing a team that doesn't exist in the DB -> the FK
    # was already satisfied at fixture-creation time here, so instead we
    # simulate an unusable record a different way: delete its league_id
    # reference indirectly isn't possible without breaking the FK, so we
    # corrupt it after the fact via a stand-in fixture object with a bad id.
    class _BrokenFixture:
        id = 999
        home_team_id = 1
        away_team_id = 2
        kickoff = None  # will raise a TypeError when compared

    summary = compute_and_store_features_for_fixtures(
        db_session, [good_a, _BrokenFixture(), good_b], commit=False
    )
    db_session.flush()

    assert summary.fetched == 3
    assert summary.upserted == 2
    assert summary.failed == 1

    assert db_session.execute(select(MatchFeatures).where(MatchFeatures.fixture_id == 2)).scalar_one_or_none()
    assert db_session.execute(select(MatchFeatures).where(MatchFeatures.fixture_id == 3)).scalar_one_or_none()
