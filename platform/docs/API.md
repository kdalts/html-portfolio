# API

The backend's read-only HTTP API, consumed by the Next.js dashboard.
Implementation: `backend/app/api/`. Interactive docs (Swagger UI) are
available at `/docs` on a running server.

Every endpoint here is **read-only** — the API never accepts writes.
Data is produced entirely by the CLI pipelines documented in
`docs/SETUP.md` (ingestion, features, models, backtesting, ranking) and,
eventually, Phase 13's scheduled automation. `SPORTMONKS_API_TOKEN` and
the database connection string are never exposed to any response — the
API serves derived, already-public-shaped data only.

## CORS

Controlled by `CORS_ALLOWED_ORIGINS` (comma-separated, default
`http://localhost:3000` — the Next.js dev server). Set this to the
dashboard's real origin(s) in production; there is no wildcard default.

## Endpoints

### `GET /health`

Liveness check. `{"status": "ok"}`.

### `GET /health/sportmonks`

Verifies `SPORTMONKS_API_TOKEN` is configured and Sportmonks is
reachable (Phase 1). `502`/`503` with a descriptive error otherwise.

### `GET /api/rankings/daily?ranking_date=YYYY-MM-DD`

The stored Top N for a date (`daily_rankings`, Phase 11), joined with
fixture/team/league names and the component model probabilities
(`model_predictions`, via `daily_rankings.model_prediction_id`).

```json
{
  "ranking_date": "2024-08-17",
  "generated_at": "2024-08-17T06:00:00Z",
  "rankings": [
    {
      "rank": 1,
      "fixture_id": 12345,
      "home_team": "Arsenal",
      "away_team": "Chelsea",
      "league_name": "Premier League",
      "kickoff": "2024-08-17T15:00:00Z",
      "final_probability": 0.71,
      "poisson_probability": 0.68,
      "ml_probability": 0.74,
      "sportmonks_probability": null,
      "market_probability": 0.62,
      "edge": 0.09,
      "confidence_score": 0.66,
      "ranking_score": 0.51
    }
  ]
}
```

Returns `rankings: []` (not an error) for a date with no stored ranking.

### `GET /api/fixtures/{fixture_id}`

Match detail: both teams' rolling form (Phase 4 `team_features`), league/
head-to-head context (`match_features`), every component probability plus
`final_probability`/`edge` (`model_predictions`), a short plain-language
`explanation` (the ensemble weights and calibration method actually
used), and — when this fixture was ever part of a daily ranking —
`confidence_score`/`ranking_score` from the most recent `daily_rankings`
row for it (these two values only exist there, not on
`model_predictions`, so a fixture that was never ranked returns `null`
for both rather than a recomputed guess). `404` if the fixture doesn't
exist.

### `GET /api/leagues/performance`

Every `league_model_performance` row (Phase 11), joined with league
names, sorted by `league_reliability_score` descending. Powers the
League Performance dashboard page.

### `GET /api/models/performance`

The most recent walk-forward fold's **overall** (`segment_type='overall'`)
`backtest_results` metrics, one row per `model_type` currently backtested.

### `GET /api/backtest/runs`

Every stored `(backtest_run_id, model_type)` pair with its overall
metrics and full probability-band breakdown — the historical backtest
view, including the calibration diagnostic (predicted probability vs.
actual frequency per band) the spec requires.

### `GET /api/system/health`

Row counts for key tables and the most recent timestamp in each of the
ingestion → features → predictions → ranking pipeline stages, plus
whether `SPORTMONKS_API_TOKEN` is configured. A simple, honest picture of
"is data flowing" — not a replacement for real job/alerting
infrastructure (see `docs/DEPLOYMENT.md` for that gap).

## What's not here yet

- No write endpoints (trigger ingestion, retrain a model, etc.) — those
  are CLI-only by design (see `docs/SETUP.md`); Phase 13 automation calls
  the same CLIs directly rather than through HTTP.
- No authentication — appropriate for a read-only API serving
  already-derived, non-sensitive prediction data, but worth revisiting
  before any endpoint here accepts writes.
