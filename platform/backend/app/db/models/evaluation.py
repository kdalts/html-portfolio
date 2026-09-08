"""Backtesting and ranking output tables.

backtest_results        -- walk-forward evaluation metrics, sliced by
                            model_type and by segment (league / season /
                            probability band / home-away / overall).
league_model_performance -- per-league reliability scoring used to filter
                            leagues out of the daily ranking.
daily_rankings           -- the final Top 10 (and any other ranked
                            fixtures) produced for a given day.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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

MODEL_TYPES = ("poisson", "ml", "sportmonks", "raw_ensemble", "final")
SEGMENT_TYPES = ("overall", "league", "season", "probability_band", "home_away")
PROBABILITY_BANDS = ("50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80+")


class BacktestResult(TimestampMixin, Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[str] = mapped_column(String(64), nullable=False)

    train_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    train_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    segment_type: Mapped[str] = mapped_column(String(32), nullable=False, default="overall")
    # 'ALL' sentinel (rather than NULL) so the unique constraint below
    # actually enforces uniqueness — Postgres treats NULLs as distinct.
    segment_value: Mapped[str] = mapped_column(String(64), nullable=False, default="ALL")

    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_probability_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_frequency: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "backtest_run_id",
            "model_type",
            "segment_type",
            "segment_value",
            name="uq_backtest_results_run_model_segment",
        ),
        CheckConstraint("model_type IN " + str(MODEL_TYPES), name="ck_backtest_results_model_type_valid"),
        CheckConstraint("segment_type IN " + str(SEGMENT_TYPES), name="ck_backtest_results_segment_type_valid"),
        CheckConstraint("sample_size >= 0", name="ck_backtest_results_sample_size_nonneg"),
        CheckConstraint("test_start_date >= train_end_date", name="ck_backtest_results_no_time_overlap"),
        Index("ix_backtest_results_run_id", "backtest_run_id"),
        Index("ix_backtest_results_model_segment", "model_type", "segment_type"),
        Index("ix_backtest_results_test_window", "test_start_date", "test_end_date"),
    )


class LeagueModelPerformance(TimestampMixin, Base):
    __tablename__ = "league_model_performance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False
    )
    model_type: Mapped[str] = mapped_column(String(32), nullable=False, default="final")

    evaluation_window_start: Mapped[date] = mapped_column(Date, nullable=False)
    evaluation_window_end: Mapped[date] = mapped_column(Date, nullable=False)

    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    calibration_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    league_reliability_score: Mapped[float] = mapped_column(Float, nullable=False)
    is_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "league_id", "model_type", "evaluation_window_end", name="uq_league_model_performance_league_window"
        ),
        CheckConstraint("model_type IN " + str(MODEL_TYPES), name="ck_league_model_performance_model_type_valid"),
        CheckConstraint("sample_size >= 0", name="ck_league_model_performance_sample_size_nonneg"),
        CheckConstraint(
            "league_reliability_score >= 0 AND league_reliability_score <= 1",
            name="ck_league_model_performance_reliability_range",
        ),
        Index("ix_league_model_performance_league_id", "league_id"),
        Index("ix_league_model_performance_is_eligible", "is_eligible"),
    )


class DailyRanking(TimestampMixin, Base):
    __tablename__ = "daily_rankings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ranking_date: Mapped[date] = mapped_column(Date, nullable=False)
    fixture_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False
    )
    model_prediction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("model_predictions.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    ranking_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_probability: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    market_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(Float, nullable=True)
    league_reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("ranking_date", "fixture_id", name="uq_daily_rankings_date_fixture"),
        UniqueConstraint("ranking_date", "rank", name="uq_daily_rankings_date_rank"),
        CheckConstraint("rank >= 1", name="ck_daily_rankings_rank_positive"),
        CheckConstraint(
            "final_probability >= 0 AND final_probability <= 1", name="ck_daily_rankings_final_probability_range"
        ),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1", name="ck_daily_rankings_confidence_range"
        ),
        Index("ix_daily_rankings_ranking_date", "ranking_date"),
        Index("ix_daily_rankings_fixture_id", "fixture_id"),
    )
