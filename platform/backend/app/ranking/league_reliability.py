"""league_reliability_score: penalizes leagues with low sample size, poor
calibration, or a poor Brier score — per spec, "The ranking system should
penalise leagues where: sample size is low, calibration is poor, Brier
score is poor, historical predictive performance is weak."

`compute_reliability_score` is pure math (testable without a database).
`aggregate_league_metrics_from_backtest` is the one function here that
touches the database: it sample-size-weighted-averages Phase 7's
per-league backtest_results rows across whichever backtest_run_ids the
caller supplies (typically every fold of one walk-forward execution), so
the resulting score reflects the whole tested history, not one fold.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.evaluation import BacktestResult

# All four are reasonable, documented defaults - not yet tuned against
# real outcomes (no real historical data has been backtested in this
# session).
MIN_RELIABLE_SAMPLE_SIZE = 200  # samples at/above this stop being penalized for size
MAX_ACCEPTABLE_BRIER = 0.35  # a Brier score at/above this contributes no positive score
MAX_ACCEPTABLE_CALIBRATION_ERROR = 0.15  # 15 points average predicted-vs-actual gap
ELIGIBILITY_SCORE_THRESHOLD = 0.4
ELIGIBILITY_MIN_SAMPLE_SIZE = 30


@dataclass(frozen=True)
class LeagueReliability:
    league_id: int
    sample_size: int
    brier_score: float | None
    log_loss: float | None
    calibration_error: float | None
    hit_rate: float | None
    league_reliability_score: float
    is_eligible: bool


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_reliability_score(
    *, sample_size: int, brier_score: float | None, calibration_error: float | None
) -> float:
    """A multiplicative combination in [0, 1]: sample-size adequacy x
    Brier quality x calibration quality. Any one dimension being poor
    pulls the whole score down (multiplicative, not additive) - a league
    with plenty of samples but badly miscalibrated predictions should not
    average out to a middling score, it should be penalized hard."""
    if sample_size <= 0:
        return 0.0
    sample_factor = min(sample_size / MIN_RELIABLE_SAMPLE_SIZE, 1.0)
    brier_factor = 1.0 - _clip01(brier_score / MAX_ACCEPTABLE_BRIER) if brier_score is not None else 1.0
    calibration_factor = (
        1.0 - _clip01(calibration_error / MAX_ACCEPTABLE_CALIBRATION_ERROR)
        if calibration_error is not None
        else 1.0
    )
    return _clip01(sample_factor * brier_factor * calibration_factor)


def _weighted_average(rows: list[BacktestResult], attr: str) -> float | None:
    values = [(getattr(r, attr), r.sample_size) for r in rows if getattr(r, attr) is not None]
    weight_sum = sum(w for _, w in values)
    return (sum(v * w for v, w in values) / weight_sum) if weight_sum else None


def aggregate_league_metrics_from_backtest(
    session: Session, *, backtest_run_ids: list[str], model_type: str
) -> dict[int, LeagueReliability]:
    rows = session.execute(
        select(BacktestResult).where(
            BacktestResult.backtest_run_id.in_(backtest_run_ids),
            BacktestResult.segment_type == "league",
            BacktestResult.model_type == model_type,
        )
    ).scalars().all()

    by_league: dict[int, list[BacktestResult]] = {}
    for row in rows:
        by_league.setdefault(int(row.segment_value), []).append(row)

    results: dict[int, LeagueReliability] = {}
    for league_id, league_rows in by_league.items():
        total_n = sum(r.sample_size for r in league_rows)
        if total_n == 0:
            continue

        brier = _weighted_average(league_rows, "brier_score")
        calibration = _weighted_average(league_rows, "calibration_error")
        score = compute_reliability_score(sample_size=total_n, brier_score=brier, calibration_error=calibration)

        results[league_id] = LeagueReliability(
            league_id=league_id,
            sample_size=total_n,
            brier_score=brier,
            log_loss=_weighted_average(league_rows, "log_loss"),
            calibration_error=calibration,
            hit_rate=_weighted_average(league_rows, "hit_rate"),
            league_reliability_score=score,
            is_eligible=score >= ELIGIBILITY_SCORE_THRESHOLD and total_n >= ELIGIBILITY_MIN_SAMPLE_SIZE,
        )
    return results
