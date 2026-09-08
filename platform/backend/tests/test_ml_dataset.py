"""Integration tests for feature matrix assembly, against a real
PostgreSQL database."""

from datetime import datetime, timezone

from app.db.models.features import MatchFeatures, TeamFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team
from app.models.dataset import META_COLUMNS, build_feature_row_for_fixture, build_training_matrix

UTC = timezone.utc
NOW = datetime.now(UTC)


def _seed_fixture(session, fixture_id, kickoff, *, home_goals=None, away_goals=None, status="NS"):
    session.add(Fixture(
        id=fixture_id, league_id=1, season_id=1, kickoff=kickoff,
        home_team_id=1, away_team_id=2, home_goals=home_goals, away_goals=away_goals, status=status,
    ))
    session.flush()
    fixture = session.get(Fixture, fixture_id)
    session.add(TeamFeatures(
        team_id=1, fixture_id=fixture_id, is_home=True, as_of=kickoff, computed_at=NOW,
        overall_last10_goals_scored=2.0,
    ))
    session.add(TeamFeatures(
        team_id=2, fixture_id=fixture_id, is_home=False, as_of=kickoff, computed_at=NOW,
        overall_last10_goals_scored=1.0,
    ))
    session.add(MatchFeatures(fixture_id=fixture_id, league_avg_goals=2.5, computed_at=NOW))
    session.flush()
    return fixture


def _seed_base(session):
    session.add(League(id=1, name="Premier League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    session.add(Team(id=1, name="Home FC"))
    session.add(Team(id=2, name="Away FC"))
    session.flush()


def test_build_training_matrix_includes_only_finished_fixtures_with_features(db_session):
    _seed_base(db_session)
    _seed_fixture(db_session, 1, datetime(2024, 8, 1, tzinfo=UTC), home_goals=2, away_goals=1, status="FT")
    _seed_fixture(db_session, 2, datetime(2024, 8, 8, tzinfo=UTC), status="NS")  # no result yet

    df = build_training_matrix(db_session, start_date=datetime(2024, 1, 1, tzinfo=UTC), end_date=datetime(2025, 1, 1, tzinfo=UTC))
    assert len(df) == 1
    assert df.iloc[0]["fixture_id"] == 1
    assert df.iloc[0]["over_2_5"] == 1


def test_build_training_matrix_column_prefixes(db_session):
    _seed_base(db_session)
    _seed_fixture(db_session, 1, datetime(2024, 8, 1, tzinfo=UTC), home_goals=2, away_goals=1, status="FT")

    df = build_training_matrix(db_session, start_date=datetime(2024, 1, 1, tzinfo=UTC), end_date=datetime(2025, 1, 1, tzinfo=UTC))
    assert df.iloc[0]["home_overall_last10_goals_scored"] == 2.0
    assert df.iloc[0]["away_overall_last10_goals_scored"] == 1.0
    assert df.iloc[0]["league_avg_goals"] == 2.5
    # no raw (unprefixed) team_features columns leaked through
    assert "overall_last10_goals_scored" not in df.columns
    # no ORM bookkeeping columns leaked through
    assert "home_id" not in df.columns
    assert "home_team_id" not in df.columns


def test_build_training_matrix_respects_date_range(db_session):
    _seed_base(db_session)
    _seed_fixture(db_session, 1, datetime(2023, 1, 1, tzinfo=UTC), home_goals=1, away_goals=1, status="FT")
    _seed_fixture(db_session, 2, datetime(2024, 8, 1, tzinfo=UTC), home_goals=2, away_goals=2, status="FT")

    df = build_training_matrix(db_session, start_date=datetime(2024, 1, 1, tzinfo=UTC), end_date=datetime(2025, 1, 1, tzinfo=UTC))
    assert list(df["fixture_id"]) == [2]


def test_build_training_matrix_ordered_by_kickoff(db_session):
    _seed_base(db_session)
    _seed_fixture(db_session, 2, datetime(2024, 8, 8, tzinfo=UTC), home_goals=0, away_goals=0, status="FT")
    _seed_fixture(db_session, 1, datetime(2024, 8, 1, tzinfo=UTC), home_goals=1, away_goals=1, status="FT")

    df = build_training_matrix(db_session, start_date=datetime(2024, 1, 1, tzinfo=UTC), end_date=datetime(2025, 1, 1, tzinfo=UTC))
    assert list(df["fixture_id"]) == [1, 2]  # chronological, not insertion order


def test_build_feature_row_for_fixture_works_for_upcoming_fixture(db_session):
    _seed_base(db_session)
    fixture = _seed_fixture(db_session, 1, datetime(2024, 8, 1, tzinfo=UTC), status="NS")
    row = build_feature_row_for_fixture(db_session, fixture)
    assert row is not None
    assert row["home_overall_last10_goals_scored"] == 2.0
    assert "over_2_5" not in row  # no target for an unplayed fixture - prediction input only


def test_build_feature_row_for_fixture_none_without_features(db_session):
    _seed_base(db_session)
    fixture = Fixture(
        id=1, league_id=1, season_id=1, kickoff=datetime(2024, 8, 1, tzinfo=UTC),
        home_team_id=1, away_team_id=2, status="NS",
    )
    db_session.add(fixture)
    db_session.flush()
    assert build_feature_row_for_fixture(db_session, fixture) is None


def test_meta_columns_are_excluded_from_feature_set(db_session):
    _seed_base(db_session)
    _seed_fixture(db_session, 1, datetime(2024, 8, 1, tzinfo=UTC), home_goals=2, away_goals=1, status="FT")
    df = build_training_matrix(db_session, start_date=datetime(2024, 1, 1, tzinfo=UTC), end_date=datetime(2025, 1, 1, tzinfo=UTC))
    assert META_COLUMNS <= set(df.columns)
