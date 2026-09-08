"""Pydantic response models for the read API. These are deliberately
read-only, hand-picked views over the ORM models — never the ORM objects
themselves — so the frontend contract stays stable even if internal
column sets change, and so nothing internal (raw feature-store rows,
timestamps meant only for auditing) leaks into the API surface by
accident.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    # Several response fields are named model_version/model_type, which
    # pydantic would otherwise warn about colliding with its own reserved
    # "model_" attribute namespace - these are plain data fields, not
    # pydantic internals, so that protection is disabled here.
    model_config = ConfigDict(protected_namespaces=())


class RankingEntry(_ApiModel):
    rank: int
    fixture_id: int
    home_team: str
    away_team: str
    league_name: str
    kickoff: datetime
    final_probability: float
    poisson_probability: float | None
    ml_probability: float | None
    sportmonks_probability: float | None
    market_probability: float | None
    edge: float | None
    confidence_score: float
    ranking_score: float


class DailyRankingResponse(_ApiModel):
    ranking_date: date
    generated_at: datetime | None
    rankings: list[RankingEntry]


class TeamRollingForm(_ApiModel):
    team_id: int
    team_name: str
    is_home: bool
    overall_last5_goals_scored: float | None
    overall_last5_goals_conceded: float | None
    overall_last5_over_2_5_pct: float | None
    overall_last5_btts_pct: float | None
    venue_last5_goals_scored: float | None
    venue_last5_goals_conceded: float | None
    venue_last5_over_2_5_pct: float | None
    venue_last10_matches_played: int | None
    overall_last10_xg: float | None
    overall_last10_xga: float | None


class MatchFeatureSummary(_ApiModel):
    league_avg_goals: float | None
    league_over_2_5_pct: float | None
    league_home_goals_avg: float | None
    league_away_goals_avg: float | None
    league_sample_size: int | None
    h2h_matches_played: int | None
    h2h_avg_total_goals: float | None
    h2h_over_2_5_pct: float | None
    h2h_btts_pct: float | None
    data_completeness_score: float | None


class ModelPredictionSummary(_ApiModel):
    model_version: str
    expected_home_goals: float | None
    expected_away_goals: float | None
    poisson_probability: float | None
    ml_probability: float | None
    sportmonks_probability: float | None
    raw_ensemble_probability: float | None
    ensemble_weights: dict | None
    calibration_method: str | None
    final_probability: float | None
    market_probability: float | None
    market_odds_over: float | None
    market_odds_under: float | None
    edge: float | None
    explanation: str


class FixtureDetailResponse(_ApiModel):
    fixture_id: int
    home_team: str
    away_team: str
    league_name: str
    kickoff: datetime
    status: str
    home_goals: int | None
    away_goals: int | None
    total_goals: int | None
    over_2_5: bool | None
    home_form: TeamRollingForm | None
    away_form: TeamRollingForm | None
    match_features: MatchFeatureSummary | None
    prediction: ModelPredictionSummary | None
    confidence_score: float | None
    ranking_score: float | None


class LeaguePerformanceEntry(_ApiModel):
    league_id: int
    league_name: str
    model_type: str
    evaluation_window_start: date
    evaluation_window_end: date
    sample_size: int
    brier_score: float | None
    log_loss: float | None
    calibration_error: float | None
    hit_rate: float | None
    league_reliability_score: float
    is_eligible: bool


class ModelPerformanceEntry(_ApiModel):
    model_type: str
    backtest_run_id: str
    test_start_date: date
    test_end_date: date
    sample_size: int
    log_loss: float | None
    brier_score: float | None
    roc_auc: float | None
    accuracy: float | None
    precision_score: float | None
    recall_score: float | None
    calibration_error: float | None
    hit_rate: float | None


class ProbabilityBandEntry(_ApiModel):
    band: str
    predicted_probability_mean: float | None
    actual_frequency: float | None
    sample_size: int


class BacktestRunSummary(_ApiModel):
    backtest_run_id: str
    model_type: str
    train_start_date: date
    train_end_date: date
    test_start_date: date
    test_end_date: date
    overall: ModelPerformanceEntry | None
    probability_bands: list[ProbabilityBandEntry]


class SystemHealthResponse(_ApiModel):
    status: str
    database_connected: bool
    sportmonks_token_configured: bool
    counts: dict[str, int]
    latest: dict[str, datetime | None]
