// Mirrors backend/app/api/schemas.py. Kept as plain interfaces (not
// generated) since the API surface is small and stable; if it grows,
// generating these from the FastAPI OpenAPI schema would be worth doing.

export interface RankingEntry {
  rank: number;
  fixture_id: number;
  home_team: string;
  away_team: string;
  league_name: string;
  kickoff: string;
  final_probability: number;
  poisson_probability: number | null;
  ml_probability: number | null;
  sportmonks_probability: number | null;
  market_probability: number | null;
  edge: number | null;
  confidence_score: number;
  ranking_score: number;
}

export interface DailyRankingResponse {
  ranking_date: string;
  generated_at: string | null;
  rankings: RankingEntry[];
}

export interface TeamRollingForm {
  team_id: number;
  team_name: string;
  is_home: boolean;
  overall_last5_goals_scored: number | null;
  overall_last5_goals_conceded: number | null;
  overall_last5_over_2_5_pct: number | null;
  overall_last5_btts_pct: number | null;
  venue_last5_goals_scored: number | null;
  venue_last5_goals_conceded: number | null;
  venue_last5_over_2_5_pct: number | null;
  venue_last10_matches_played: number | null;
  overall_last10_xg: number | null;
  overall_last10_xga: number | null;
}

export interface MatchFeatureSummary {
  league_avg_goals: number | null;
  league_over_2_5_pct: number | null;
  league_home_goals_avg: number | null;
  league_away_goals_avg: number | null;
  league_sample_size: number | null;
  h2h_matches_played: number | null;
  h2h_avg_total_goals: number | null;
  h2h_over_2_5_pct: number | null;
  h2h_btts_pct: number | null;
  data_completeness_score: number | null;
}

export interface ModelPredictionSummary {
  model_version: string;
  expected_home_goals: number | null;
  expected_away_goals: number | null;
  poisson_probability: number | null;
  ml_probability: number | null;
  sportmonks_probability: number | null;
  raw_ensemble_probability: number | null;
  ensemble_weights: Record<string, number> | null;
  calibration_method: string | null;
  final_probability: number | null;
  market_probability: number | null;
  market_odds_over: number | null;
  market_odds_under: number | null;
  edge: number | null;
  explanation: string;
}

export interface FixtureDetailResponse {
  fixture_id: number;
  home_team: string;
  away_team: string;
  league_name: string;
  kickoff: string;
  status: string;
  home_goals: number | null;
  away_goals: number | null;
  total_goals: number | null;
  over_2_5: boolean | null;
  home_form: TeamRollingForm | null;
  away_form: TeamRollingForm | null;
  match_features: MatchFeatureSummary | null;
  prediction: ModelPredictionSummary | null;
  confidence_score: number | null;
  ranking_score: number | null;
}

export interface LeaguePerformanceEntry {
  league_id: number;
  league_name: string;
  model_type: string;
  evaluation_window_start: string;
  evaluation_window_end: string;
  sample_size: number;
  brier_score: number | null;
  log_loss: number | null;
  calibration_error: number | null;
  hit_rate: number | null;
  league_reliability_score: number;
  is_eligible: boolean;
}

export interface ModelPerformanceEntry {
  model_type: string;
  backtest_run_id: string;
  test_start_date: string;
  test_end_date: string;
  sample_size: number;
  log_loss: number | null;
  brier_score: number | null;
  roc_auc: number | null;
  accuracy: number | null;
  precision_score: number | null;
  recall_score: number | null;
  calibration_error: number | null;
  hit_rate: number | null;
}

export interface ProbabilityBandEntry {
  band: string;
  predicted_probability_mean: number | null;
  actual_frequency: number | null;
  sample_size: number;
}

export interface BacktestRunSummary {
  backtest_run_id: string;
  model_type: string;
  train_start_date: string;
  train_end_date: string;
  test_start_date: string;
  test_end_date: string;
  overall: ModelPerformanceEntry | null;
  probability_bands: ProbabilityBandEntry[];
}

export interface SystemHealthResponse {
  status: string;
  database_connected: boolean;
  sportmonks_token_configured: boolean;
  counts: Record<string, number>;
  latest: Record<string, string | null>;
}
