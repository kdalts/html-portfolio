"""Reference entities: leagues, teams, seasons.

Primary keys are the Sportmonks entity IDs themselves (not surrogate
auto-increment IDs). This keeps ingestion idempotent: upserts key directly
on the ID Sportmonks returns, with no separate ID-mapping table required.
"""

from sqlalchemy import BigInteger, Boolean, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class League(TimestampMixin, Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Sportmonks league id
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    seasons: Mapped[list["Season"]] = relationship(back_populates="league")

    __table_args__ = (Index("ix_leagues_country_id", "country_id"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"League(id={self.id!r}, name={self.name!r})"


class Team(TimestampMixin, Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Sportmonks team id
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    country_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    founded: Mapped[int | None] = mapped_column(nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    __table_args__ = (Index("ix_teams_country_id", "country_id"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Team(id={self.id!r}, name={self.name!r})"


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Sportmonks season id
    league_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leagues.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "2023/2024"
    start_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    league: Mapped["League"] = relationship(back_populates="seasons")

    __table_args__ = (Index("ix_seasons_league_id", "league_id"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Season(id={self.id!r}, league_id={self.league_id!r}, name={self.name!r})"
