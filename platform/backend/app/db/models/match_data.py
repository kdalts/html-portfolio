"""Per-fixture match data captured from Sportmonks: box-score statistics,
xG, Sportmonks' own predictions, and bookmaker odds.

`sportmonks_predictions` and `odds` both carry a `retrieved_at` timestamp.
This is the leakage guard for these tables: feature/prediction generation
code must only use rows whose retrieved_at <= the fixture's kickoff. It is
enforced at the application layer (tested in later phases) because
PostgreSQL CHECK constraints cannot reference another table's columns.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MatchStatistics(TimestampMixin, Base):
    """Box-score style stats for one team in one fixture."""

    __tablename__ = "match_statistics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False)

    shots_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shots_on_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    big_chances_created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    possession_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    fouls: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yellow_cards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    red_cards: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("fixture_id", "team_id", name="uq_match_statistics_fixture_team"),
        Index("ix_match_statistics_team_id", "team_id"),
        CheckConstraint(
            "possession_percentage IS NULL OR (possession_percentage >= 0 AND possession_percentage <= 100)",
            name="ck_match_statistics_possession_range",
        ),
    )


class MatchXG(TimestampMixin, Base):
    """Expected-goals data for one team in one fixture.

    A team's xGA (expected goals against) for this fixture is the
    opponent's xg row for the same fixture_id — deliberately not
    duplicated here to avoid two rows disagreeing with each other.
    """

    __tablename__ = "match_xg"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False)
    xg: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="sportmonks")

    __table_args__ = (
        UniqueConstraint("fixture_id", "team_id", name="uq_match_xg_fixture_team"),
        Index("ix_match_xg_team_id", "team_id"),
        CheckConstraint("xg IS NULL OR xg >= 0", name="ck_match_xg_nonneg"),
    )


class SportmonksPrediction(TimestampMixin, Base):
    """Sportmonks' own pre-match model outputs for a fixture, as pulled at
    a specific point in time (retrieved_at)."""

    __tablename__ = "sportmonks_predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    over_2_5_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    btts_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_home_goals: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_away_goals: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "over_2_5_probability IS NULL OR (over_2_5_probability >= 0 AND over_2_5_probability <= 1)",
            name="ck_sportmonks_predictions_over_2_5_range",
        ),
        CheckConstraint(
            "btts_probability IS NULL OR (btts_probability >= 0 AND btts_probability <= 1)",
            name="ck_sportmonks_predictions_btts_range",
        ),
        Index("ix_sportmonks_predictions_retrieved_at", "retrieved_at"),
    )


class Odds(TimestampMixin, Base):
    """A bookmaker odds snapshot for the Over/Under 2.5 goals market,
    captured at retrieved_at. Multiple snapshots per fixture are expected
    (odds move pre-kickoff); the raw implied probability, de-vig market
    probability, and overround are derived columns computed by the
    database from over_odds/under_odds so they can never disagree with
    the stored prices."""

    __tablename__ = "odds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False
    )
    bookmaker: Mapped[str] = mapped_column(String(64), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False, default="over_under_2_5")
    over_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    under_odds: Mapped[float | None] = mapped_column(Float, nullable=True)
    over_implied_probability: Mapped[float | None] = mapped_column(
        Float, Computed("CASE WHEN over_odds > 0 THEN 1.0 / over_odds ELSE NULL END", persisted=True), nullable=True
    )
    under_implied_probability: Mapped[float | None] = mapped_column(
        Float,
        Computed("CASE WHEN under_odds > 0 THEN 1.0 / under_odds ELSE NULL END", persisted=True),
        nullable=True,
    )
    overround: Mapped[float | None] = mapped_column(
        Float,
        Computed(
            "CASE WHEN over_odds > 0 AND under_odds > 0 "
            "THEN (1.0 / over_odds) + (1.0 / under_odds) ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    market_probability: Mapped[float | None] = mapped_column(
        Float,
        Computed(
            "CASE WHEN over_odds > 0 AND under_odds > 0 "
            "THEN (1.0 / over_odds) / ((1.0 / over_odds) + (1.0 / under_odds)) ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "fixture_id", "bookmaker", "market", "retrieved_at", name="uq_odds_fixture_bookmaker_market_snapshot"
        ),
        CheckConstraint("over_odds IS NULL OR over_odds > 1", name="ck_odds_over_odds_valid"),
        CheckConstraint("under_odds IS NULL OR under_odds > 1", name="ck_odds_under_odds_valid"),
        Index("ix_odds_fixture_id", "fixture_id"),
        Index("ix_odds_retrieved_at", "retrieved_at"),
    )
