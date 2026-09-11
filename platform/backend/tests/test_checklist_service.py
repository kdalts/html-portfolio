"""Real-PostgreSQL integration tests for the checklist service: proves
data actually flows correctly from fixtures/results into the check
functions (the pure math itself is exhaustively covered in
test_checklist_checks.py), the leakage boundary holds, the sample-size
exclusion works, and the batch driver stores/records results correctly.

Synthetic setup: a tiny 2-team "league" where the same two teams meet 5
times before the target (6th) fixture - unrealistic for a real season,
but it lets one set of fixtures simultaneously exercise season sample
size, head-to-head, and standings with hand-checkable numbers, the same
simplification pattern used elsewhere in this codebase's tests (e.g.
Phase 13's daily-pipeline test)."""

from datetime import datetime, timedelta, timezone

from app.checklist.service import compute_and_store_checklist_for_fixtures, compute_checklist_for_fixture
from app.db.models.checklist import ChecklistScore
from app.db.models.features import MatchFeatures
from app.db.models.fixtures import Fixture
from app.db.models.leagues_teams import League, Season, Team

UTC = timezone.utc
BASE = datetime(2024, 8, 1, tzinfo=UTC)
TARGET_KICKOFF = BASE + timedelta(days=10)


def _seed_common(session):
    session.add(League(id=1, name="Test League"))
    session.add(Season(id=1, league_id=1, name="2024/2025"))
    session.add(Team(id=10, name="Home FC"))
    session.add(Team(id=11, name="Away FC"))
    session.flush()


def _seed_prior_meetings(session, *, count, home_goals=4, away_goals=1):
    for i in range(count):
        session.add(
            Fixture(
                id=1000 + i,
                league_id=1,
                season_id=1,
                kickoff=BASE + timedelta(days=i),
                home_team_id=10,
                away_team_id=11,
                home_goals=home_goals,
                away_goals=away_goals,
                status="FT",
            )
        )
    session.flush()


def test_compute_checklist_for_a_well_populated_fixture(db_session):
    _seed_common(db_session)
    _seed_prior_meetings(db_session, count=5)  # each a 4-1 home win, all before the target kickoff

    target = Fixture(
        id=2000, league_id=1, season_id=1, kickoff=TARGET_KICKOFF, home_team_id=10, away_team_id=11, status="NS",
    )
    db_session.add(target)
    db_session.flush()
    db_session.add(
        MatchFeatures(
            fixture_id=2000, league_home_goals_avg=1.0, league_away_goals_avg=0.5, computed_at=datetime.now(UTC)
        )
    )
    db_session.flush()

    result = compute_checklist_for_fixture(db_session, target)
    assert result is not None

    # hand-computed from the five 4-1 home wins (see module docstring for the numbers):
    assert result["sample_size_ok"] is True
    assert result["btts_rate_ok"] is True  # both teams scored in every prior meeting
    assert result["clean_sheet_rate_ok"] is True  # neither team ever kept a clean sheet (0% < 35%)
    assert result["combined_goals_ok"] is True  # 5.0 + 5.0 = 10 > 3.5
    assert result["league_gap_ok"] is False  # only 2 teams in this table - gap is 1, not >= 5
    assert result["shots_on_target_ok"] is None  # no match_statistics ingested - honest N/A, not a guess
    assert result["attack_defence_split_ok"] is True  # home GF avg 4.0 > 3, away GA avg 4.0 > 3
    assert result["xg_ok"] is None  # no match_xg ingested - honest N/A
    assert result["h2h_ok"] is True  # last 3 of the 5 prior meetings were all 5-goal games
    assert result["recent_form_ok"] is True  # last 5 games for both teams were all over 2.5
    assert result["vs_league_avg_ok"] is True  # 4.0 > 1.0 and 1.0 > 0.5
    assert result["early_goals_ok"] is None  # no goal-timing data exists anywhere in this platform yet
    assert result["late_goals_ok"] is None

    assert result["checks_computable"] == 9  # 13 minus the 4 always/currently-N/A checks above
    assert result["checks_passed"] == 8  # every computable check passed except league_gap
    assert result["score_pct"] == 8 / 9
    assert result["key_players_missing"] == "Unknown"
    assert "shots-on-target" in result["data_gaps"]
    assert "xG" in result["data_gaps"]


def test_fixtures_own_result_never_leaks_into_its_own_checklist(db_session):
    """The target fixture is marked FT with a real score, but computing
    ITS OWN checklist must only ever see the 5 prior meetings, never this
    result - proven directly, same leakage discipline as Phase 4."""
    _seed_common(db_session)
    _seed_prior_meetings(db_session, count=5)

    target = Fixture(
        id=2000, league_id=1, season_id=1, kickoff=TARGET_KICKOFF, home_team_id=10, away_team_id=11,
        home_goals=0, away_goals=0, status="FT",  # a 0-0 draw, deliberately unlike the prior 4-1 pattern
    )
    db_session.add(target)
    db_session.flush()
    db_session.add(
        MatchFeatures(
            fixture_id=2000, league_home_goals_avg=1.0, league_away_goals_avg=0.5, computed_at=datetime.now(UTC)
        )
    )
    db_session.flush()

    result = compute_checklist_for_fixture(db_session, target)
    # if the 0-0 result had leaked in, btts/combined-goals/recent-form would
    # all flip to False - they don't, because it never enters the computation.
    assert result["btts_rate_ok"] is True
    assert result["combined_goals_ok"] is True
    assert result["recent_form_ok"] is True


def test_fixture_with_too_few_season_games_is_excluded_not_scored(db_session):
    _seed_common(db_session)
    _seed_prior_meetings(db_session, count=3)  # below MIN_SEASON_GAMES = 5

    target = Fixture(
        id=2000, league_id=1, season_id=1, kickoff=TARGET_KICKOFF, home_team_id=10, away_team_id=11, status="NS",
    )
    db_session.add(target)
    db_session.flush()

    assert compute_checklist_for_fixture(db_session, target) is None


def test_batch_driver_stores_qualifying_fixtures_and_records_excluded_ones(db_session):
    _seed_common(db_session)
    _seed_prior_meetings(db_session, count=5)

    qualifying = Fixture(
        id=2000, league_id=1, season_id=1, kickoff=TARGET_KICKOFF, home_team_id=10, away_team_id=11, status="NS",
    )
    db_session.add_all([qualifying, Team(id=12, name="Newcomer FC")])
    db_session.flush()
    db_session.add(
        MatchFeatures(
            fixture_id=2000, league_home_goals_avg=1.0, league_away_goals_avg=0.5, computed_at=datetime.now(UTC)
        )
    )
    excluded = Fixture(
        id=2001, league_id=1, season_id=1, kickoff=TARGET_KICKOFF, home_team_id=12, away_team_id=11, status="NS",
    )
    db_session.add(excluded)
    db_session.flush()

    summary = compute_and_store_checklist_for_fixtures(db_session, [qualifying, excluded], commit=False)

    assert summary.fetched == 2
    assert summary.upserted == 1
    assert summary.failed == 1
    assert "excluded" in summary.errors[0]

    stored = db_session.query(ChecklistScore).filter_by(fixture_id=2000).one_or_none()
    assert stored is not None
    assert db_session.query(ChecklistScore).filter_by(fixture_id=2001).one_or_none() is None

    # idempotent re-run: same fixture, no duplicate row
    compute_and_store_checklist_for_fixtures(db_session, [qualifying], commit=False)
    assert db_session.query(ChecklistScore).filter_by(fixture_id=2000).count() == 1
