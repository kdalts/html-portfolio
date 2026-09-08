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
| `TEST_DATABASE_URL` | No (tests only) | `postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test` | DB used by `tests/test_db_integration.py` |

Further phases will add more variables, documented here as they are
introduced.
