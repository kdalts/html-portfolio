"""checklist_scores: a second, independent scoring system alongside the
main probability/confidence/edge pipeline — a fixed 15-point rule
checklist (BTTS rate, clean sheet rate, combined goals, league position
gap, shots on target, xG, head-to-head, recent form, and so on), each
check TRUE/FALSE/N/A rather than a probability estimate.

One row per fixture (recomputing upserts in place, same idempotent
pattern as model_predictions). The 13 boolean columns below correspond
to checklist items 1-13, which count toward `checks_passed` /
`checks_computable`; items 14-15 (missing players, context notes) are
informational only and never contribute to the score - see
app/checklist/checks.py's CHECK_LABELS for the full item-number mapping.

`checks_passed`, `checks_computable`, and `score_pct` are computed in
Python (app/checklist/service.py), not as PostgreSQL generated columns:
Postgres generated columns cannot reference other generated columns, and
expressing "count TRUE among 13 nullable booleans" three times over would
be far more error-prone than computing it once in the same place the
checks themselves run — the same reasoning already applied to
confidence_score/ranking_score in Phase 11.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ChecklistScore(TimestampMixin, Base):
    __tablename__ = "checklist_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fixture_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fixtures.id", ondelete="CASCADE"), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Checklist items 1-13 (scored). NULL = N/A (not computable), not False. ---
    sample_size_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    btts_rate_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    clean_sheet_rate_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    combined_goals_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    league_gap_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    shots_on_target_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attack_defence_split_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    xg_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    h2h_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    recent_form_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    vs_league_avg_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    early_goals_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    late_goals_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    checks_passed: Mapped[int] = mapped_column(Integer, nullable=False)
    checks_computable: Mapped[int] = mapped_column(Integer, nullable=False)
    score_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Items 14-15 (informational, never scored) ---
    key_players_missing: Mapped[str] = mapped_column(Text, nullable=False, default="Unknown")
    context_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_gaps: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("fixture_id", name="uq_checklist_scores_fixture"),
        CheckConstraint("checks_passed >= 0 AND checks_passed <= 13", name="ck_checklist_scores_passed_range"),
        CheckConstraint(
            "checks_computable >= 0 AND checks_computable <= 13", name="ck_checklist_scores_computable_range"
        ),
        CheckConstraint("checks_passed <= checks_computable", name="ck_checklist_scores_passed_le_computable"),
        CheckConstraint(
            "score_pct IS NULL OR (score_pct >= 0 AND score_pct <= 1)", name="ck_checklist_scores_score_pct_range"
        ),
        Index("ix_checklist_scores_computed_at", "computed_at"),
        Index("ix_checklist_scores_score_pct", "score_pct"),
    )
