"""Engineered feature store.

`team_features` holds one row per (team, fixture): that team's rolling
pre-match form entering that specific fixture, computed strictly from
matches whose kickoff was before this fixture's kickoff. Two contexts are
stored side by side:

  - "overall_lastN_*"  — rolling form across the team's last N matches
    regardless of venue.
  - "venue_lastN_*"    — rolling form across the team's last N matches in
    the SAME venue role as this fixture (home matches only if this team is
    the home team here, away matches only if it is the away team here).
    This directly implements "home-team home-performance features" /
    "away-team away-performance features" from the spec.

Each (context, window) pair also stores a *_matches_played sample-size
column, because early-season teams may have fewer than N prior matches
available — consumers must be able to tell a true 0% rate from "no data".

`match_features` holds the fixture-level features that are NOT specific to
a single team: league context and head-to-head (matchup) history. The two
teams' rolling form is obtained by joining team_features on
(fixture_id, fixtures.home_team_id / fixtures.away_team_id) rather than
being duplicated into this table.

No row in either table is populated by this migration; Phase 4 (feature
engineering) is responsible for computing and writing them, using only
data available before each fixture's kickoff.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

STAT_KEYS: tuple[str, ...] = (
    "goals_scored",
    "goals_conceded",
    "xg",
    "xga",
    "shots",
    "shots_on_target",
    "big_chances",
    "corners",
    "btts_pct",
    "over_2_5_pct",
)
ROLLING_WINDOWS: tuple[int, ...] = (3, 5, 10)
FEATURE_CONTEXTS: tuple[str, ...] = ("overall", "venue")


def _team_feature_column_names() -> list[str]:
    """The full list of rolling-stat + sample-size column names on
    TeamFeatures, in the same order they are declared. Used by tests to
    assert the generated schema matches the spec (windows x stats x
    contexts) without hand-maintaining a duplicate list."""
    names: list[str] = []
    for context in FEATURE_CONTEXTS:
        for window in ROLLING_WINDOWS:
            names.append(f"{context}_last{window}_matches_played")
            for stat in STAT_KEYS:
                names.append(f"{context}_last{window}_{stat}")
    return names


def _build_team_features_namespace() -> dict:
    namespace: dict = {
        "__tablename__": "team_features",
        "id": mapped_column(BigInteger, primary_key=True, autoincrement=True),
        "team_id": mapped_column(BigInteger, ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False),
        "fixture_id": mapped_column(BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False),
        "is_home": mapped_column(Boolean, nullable=False),
        "as_of": mapped_column(DateTime(timezone=True), nullable=False),
        "feature_version": mapped_column(String(32), nullable=False, default="v1"),
        "computed_at": mapped_column(DateTime(timezone=True), nullable=False),
    }
    for context in FEATURE_CONTEXTS:
        for window in ROLLING_WINDOWS:
            namespace[f"{context}_last{window}_matches_played"] = mapped_column(Integer, nullable=True)
            for stat in STAT_KEYS:
                namespace[f"{context}_last{window}_{stat}"] = mapped_column(Float, nullable=True)

    namespace["__table_args__"] = (
        UniqueConstraint("team_id", "fixture_id", name="uq_team_features_team_fixture"),
        Index("ix_team_features_fixture_id", "fixture_id"),
        Index("ix_team_features_team_id", "team_id"),
        Index("ix_team_features_as_of", "as_of"),
    )
    return namespace


# Built programmatically: ~10 stats x 3 windows x 2 contexts (+ sample-size
# columns per window/context) would be unwieldy to hand-declare, and a
# generated column set is easy to verify for completeness (see
# test_features_schema.py) instead of eyeballing ~70 lines of columns.
TeamFeatures = type("TeamFeatures", (TimestampMixin, Base), _build_team_features_namespace())


class MatchFeatures(TimestampMixin, Base):
    """Fixture-level features not specific to a single team: league
    context and head-to-head history. One row per fixture."""

    __tablename__ = "match_features"

    fixture_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), primary_key=True
    )

    # League-level context, computed from that league's matches strictly
    # before this fixture's kickoff.
    league_avg_goals: Mapped[float | None] = mapped_column(Float, nullable=True)
    league_over_2_5_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    league_home_goals_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    league_away_goals_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
    league_sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Head-to-head / matchup features. Null when insufficient shared
    # history exists between the two teams (per spec: only computed
    # "where sufficient historical data exists").
    h2h_matches_played: Mapped[int | None] = mapped_column(Integer, nullable=True)
    h2h_avg_total_goals: Mapped[float | None] = mapped_column(Float, nullable=True)
    h2h_over_2_5_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    h2h_btts_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    feature_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_completeness_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (Index("ix_match_features_computed_at", "computed_at"),)
