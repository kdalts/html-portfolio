"""model_predictions: every probability estimate this system produces for
a fixture, plus the calibrated final output, confidence, and market edge.

Columns are deliberately kept distinct per the platform's core rule:
  - probability   -> poisson_probability / ml_probability /
                      sportmonks_probability / raw_ensemble_probability /
                      final_probability
  - confidence    -> confidence_score (never conflated with probability)
  - market edge   -> edge (final_probability - market_probability), computed
                      by the database from the two inputs so it can never
                      silently drift out of sync with them.

`predicted_at` must be strictly before the fixture's kickoff; this is
enforced at the application layer (see leakage-protection tests in later
phases) since it depends on another table's column.
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
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ModelPrediction(TimestampMixin, Base):
    __tablename__ = "model_predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)

    # --- Poisson model ---
    expected_home_goals: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_away_goals: Mapped[float | None] = mapped_column(Float, nullable=True)
    poisson_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- ML model ---
    ml_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Sportmonks model ---
    sportmonks_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Ensemble / calibration ---
    raw_ensemble_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    ensemble_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    calibration_method: Mapped[str | None] = mapped_column(String(32), nullable=True)  # 'platt' | 'isotonic' | None
    final_probability: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Confidence (distinct from probability) ---
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Market context used for this prediction's edge ---
    odds_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("odds.id", ondelete="SET NULL"), nullable=True)
    market_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_odds_over: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_odds_under: Mapped[float | None] = mapped_column(Float, nullable=True)
    edge: Mapped[float | None] = mapped_column(
        Float,
        Computed(
            "CASE WHEN final_probability IS NOT NULL AND market_probability IS NOT NULL "
            "THEN final_probability - market_probability ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )

    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("fixture_id", "model_version", name="uq_model_predictions_fixture_version"),
        CheckConstraint(
            "poisson_probability IS NULL OR (poisson_probability >= 0 AND poisson_probability <= 1)",
            name="ck_model_predictions_poisson_range",
        ),
        CheckConstraint(
            "ml_probability IS NULL OR (ml_probability >= 0 AND ml_probability <= 1)",
            name="ck_model_predictions_ml_range",
        ),
        CheckConstraint(
            "sportmonks_probability IS NULL OR (sportmonks_probability >= 0 AND sportmonks_probability <= 1)",
            name="ck_model_predictions_sportmonks_range",
        ),
        CheckConstraint(
            "raw_ensemble_probability IS NULL OR (raw_ensemble_probability >= 0 AND raw_ensemble_probability <= 1)",
            name="ck_model_predictions_raw_ensemble_range",
        ),
        CheckConstraint(
            "final_probability IS NULL OR (final_probability >= 0 AND final_probability <= 1)",
            name="ck_model_predictions_final_range",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_model_predictions_confidence_range",
        ),
        CheckConstraint(
            "calibration_method IS NULL OR calibration_method IN ('platt', 'isotonic', 'none')",
            name="ck_model_predictions_calibration_method_valid",
        ),
        Index("ix_model_predictions_fixture_id", "fixture_id"),
        Index("ix_model_predictions_predicted_at", "predicted_at"),
    )
