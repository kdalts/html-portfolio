# Setup

This document covers Phase 1 (Sportmonks connection), Phase 2 (database),
and Phase 3 (historical ingestion) setup. It will be extended as later
phases add models and the frontend.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ (16 recommended — generated/STORED columns require PG 12+)
- A Sportmonks Football API account and token
  (https://www.sportmonks.com/football-api/)

## 1. Get a Sportmonks API token

Sign up at Sportmonks and copy your API token from your account dashboard.
Treat it as a secret: it must never be committed to git, printed in logs,
or embedded in frontend code.

## 2. Configure the backend environment

```bash
cd platform/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
```

Edit `.env` and set:

```
SPORTMONKS_API_TOKEN=your-real-token-here
```

`.env` is git-ignored (see `backend/.gitignore`) — it is never committed.
All configuration is read from the environment via
`app/core/config.py:Settings`; nothing is hard-coded in source.

## 3. Create the databases and apply migrations

```bash
# create an app database and a separate test database
createdb football_platform
createdb football_platform_test

# set DATABASE_URL in .env, e.g.:
# DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform

cd platform/backend
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform
alembic upgrade head

export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test
alembic upgrade head
```

See `docs/DATABASE.md` for the full schema and migration workflow.

## 4. Run the tests

```bash
cd platform/backend
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test
python3 -m pytest -v
```

Sportmonks HTTP calls are mocked (`httpx.MockTransport`) — no real token or
network access needed. Database tests run against a real PostgreSQL
database (`TEST_DATABASE_URL`) and skip cleanly if one isn't reachable.

## 5. Run the API locally

```bash
cd platform/backend
uvicorn app.main:app --reload
```

Then check:

- `GET http://localhost:8000/health` → `{"status": "ok"}`
- `GET http://localhost:8000/health/sportmonks` → `{"status": "ok", "provider": "sportmonks"}`
  if `SPORTMONKS_API_TOKEN` is set and valid, or a `502`/`503` with a
  descriptive error otherwise.

See `docs/API.md` for the full read API the dashboard (below) consumes.

## 5b. Run the dashboard locally

```bash
cd platform/frontend
npm install
cp .env.example .env.local   # set API_BASE_URL if the API isn't on localhost:8000
npm run dev
```

Open http://localhost:3000. Requires the backend API (step 5) running.
See `frontend/README.md` for the page list and architecture notes.

## 6. Run historical ingestion

```bash
cd platform/backend
python3 -m app.ingestion.cli leagues
python3 -m app.ingestion.cli fixtures --start 2019-08-01 --end 2019-08-31
```

Fixture ingestion is safe to re-run (upserts are idempotent) and never
writes `sportmonks_predictions`/`odds` for historical data — see
`platform/README.md`'s Phase 3 section for why. Before relying on
`--with-statistics`, fill in the real Sportmonks `type_id`/`market_id`
values in `app/ingestion/sportmonks_reference.py` (currently placeholders).

## 7. Compute features

```bash
cd platform/backend
python3 -m app.features.cli build --start 2019-08-01 --end 2025-08-01
```

Computes `team_features`/`match_features` for every fixture kicking off in
that range — including upcoming, not-yet-played fixtures, which need
features for the daily ranking just as much as historical ones need them
for training. Safe to re-run (idempotent). See `platform/README.md`'s
Phase 4 section for how the leakage boundary is enforced.

## 8. Generate Poisson baseline predictions

```bash
cd platform/backend
python3 -m app.models.poisson_cli build --start 2019-08-01 --end 2025-08-01
```

Requires features to already be computed for those fixtures (step 7).
Writes `expected_home_goals`/`expected_away_goals`/`poisson_probability`
onto `model_predictions`. Safe to re-run.

## 9. Train and run the XGBoost model

```bash
cd platform/backend
python3 -m app.models.ml_cli train --train-start 2019-08-01 --train-end 2023-08-01 --val-end 2024-08-01
python3 -m app.models.ml_cli predict --start 2024-08-01 --end 2024-09-01
```

Training only uses fixtures with a known result and computed features
(chronologically split — never shuffled). Saves a model artifact under
`backend/artifacts/xgboost/` (git-ignored). `predict` requires a trained
artifact and writes `ml_probability` onto `model_predictions`, merging
into the same row Poisson wrote to.

## 10. Run a walk-forward backtest

```bash
cd platform/backend
python3 -m app.backtest.cli run
```

Writes `backtest_results` rows for the expanding-window folds described
in `docs/BACKTEST.md`. Each fold trains its own ML artifact (under
`backend/artifacts/xgboost/backtest/`) using only that fold's training
window — never the shared "production" `v1` model.

## 11. Fit and apply the ensemble + calibration

```bash
cd platform/backend
python3 -m app.models.ensemble_cli fit --val-start 2023-08-01 --val-end 2024-08-01
python3 -m app.models.ensemble_cli apply --start 2024-08-01 --end 2024-09-01
```

`fit` reads already-stored `model_predictions` (poisson/ml, and
sportmonks once Phase 9 populates it) for the validation window, fits
ensemble weights and selects a calibration method, and saves an artifact
under `backend/artifacts/ensemble/`. `apply` writes
`raw_ensemble_probability`/`final_probability` onto `model_predictions`
for fixtures in range, merging into the existing row.

## 12. Sync Sportmonks predictions

```bash
cd platform/backend
python3 -m app.models.sportmonks_cli sync --start 2024-08-01 --end 2024-09-01
```

Copies each fixture's already-ingested `sportmonks_predictions.over_2_5_probability`
(from step 6's ingestion, near-kickoff use case) onto
`model_predictions.sportmonks_probability`. Run this before step 11's
`fit` so the ensemble can see it.

## 13. Sync market odds

```bash
cd platform/backend
python3 -m app.models.odds_cli sync --start 2024-08-01 --end 2024-09-01
```

Picks the latest plausible odds snapshot per bookmaker (from step 6's
odds ingestion) and writes `market_probability`/`market_odds_over`/
`market_odds_under` onto `model_predictions` — `edge` then follows
automatically as a generated column once `final_probability` is also set.

## 14. Compute league reliability and the daily ranking

```bash
cd platform/backend
python3 -m app.ranking.cli league-reliability \
  --run-ids wf-2026-2023,wf-2026-2024,wf-2026-2025 --model-type poisson \
  --window-start 2019-01-01 --window-end 2025-01-01

python3 -m app.ranking.cli daily --date 2024-08-17 --reliability-model-type poisson
```

`league-reliability` aggregates step 10's `backtest_results` into
`league_model_performance`; use the `backtest_run_ids` from that run's
log output. `daily` builds and stores the Top 10 for a date — requires
predictions (steps 8/9/11/12/13) and features (step 7) already computed
for that date's fixtures.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SPORTMONKS_API_TOKEN` | Yes | — | Sportmonks Football API token |
| `SPORTMONKS_BASE_URL` | No | `https://api.sportmonks.com/v3/football` | API base URL |
| `SPORTMONKS_TIMEOUT_SECONDS` | No | `15` | Per-request HTTP timeout |
| `SPORTMONKS_MAX_RETRIES` | No | `5` | Retries for transient failures |
| `SPORTMONKS_BACKOFF_BASE_SECONDS` | No | `1.0` | Base for exponential backoff |
| `SPORTMONKS_REQUESTS_PER_MINUTE` | No | `60` | Client-side throttle budget |
| `DATABASE_URL` | Yes | — | PostgreSQL connection string (app + Alembic) |
| `DATABASE_ECHO` | No | `false` | Log all SQL statements |
| `CORS_ALLOWED_ORIGINS` | No | `http://localhost:3000` | Comma-separated origins allowed to call the read API |
| `TEST_DATABASE_URL` | No (tests only) | `postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test` | DB used by `tests/test_db_integration.py` |

Further phases will add more variables, documented here as they are
introduced.
