"""Fixtures: the central match table.

`total_goals` and `over_2_5` are PostgreSQL STORED GENERATED columns —
they are pure, deterministic functions of `home_goals` / `away_goals`,
computed by the database itself. This is a deliberate leakage/ correctness
guard: the Over 2.5 target label can never drift from the rule

    over_2_5 = 1 if home_goals + away_goals >= 3 else 0

because no application code path can set it independently or inconsistently
with the final score, and it is NULL for any fixture that has not finished.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Sportmonks fixture status codes we accept. Extend as new codes are observed.
VALID_FIXTURE_STATUSES = (
    "NS",  # Not Started
    "LIVE",
    "HT",
    "FT",
    "AET",
    "PEN",
    "POSTP",
    "CANC",
    "ABAN",
    "SUSP",
    "TBD",
)


class Fixture(TimestampMixin, Base):
    __tablename__ = "fixtures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Sportmonks fixture id
    league_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leagues.id", ondelete="RESTRICT"), nullable=False
    )
    season_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("seasons.id", ondelete="RESTRICT"), nullable=False
    )
    kickoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    home_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_goals: Mapped[int | None] = mapped_column(
        Integer, Computed("home_goals + away_goals", persisted=True), nullable=True
    )
    over_2_5: Mapped[bool | None] = mapped_column(
        Boolean,
        Computed(
            "CASE WHEN home_goals IS NULL OR away_goals IS NULL "
            "THEN NULL ELSE (home_goals + away_goals) >= 3 END",
            persisted=True,
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="NS")

    __table_args__ = (
        CheckConstraint("home_goals IS NULL OR home_goals >= 0", name="ck_fixtures_home_goals_nonneg"),
        CheckConstraint("away_goals IS NULL OR away_goals >= 0", name="ck_fixtures_away_goals_nonneg"),
        CheckConstraint("home_team_id <> away_team_id", name="ck_fixtures_distinct_teams"),
        CheckConstraint(
            "status IN " + str(VALID_FIXTURE_STATUSES),
            name="ck_fixtures_status_valid",
        ),
        Index("ix_fixtures_kickoff", "kickoff"),
        Index("ix_fixtures_league_season", "league_id", "season_id"),
        Index("ix_fixtures_home_team", "home_team_id"),
        Index("ix_fixtures_away_team", "away_team_id"),
        Index("ix_fixtures_status", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"Fixture(id={self.id!r}, kickoff={self.kickoff!r}, status={self.status!r})"
