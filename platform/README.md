# Football Over 2.5 Goals Prediction Platform

A production-quality system that ingests football data from the Sportmonks
Football API, engineers pre-match features, produces multiple Over 2.5
Goals probability estimates (Poisson, XGBoost, Sportmonks, and a calibrated
ensemble), backtests them with strict time-based validation, and ranks
upcoming matches into a daily Top 10.

The system reports **probability**, **confidence**, and **market edge** as
distinct, separately-computed quantities. Nothing in this system claims a
prediction is certain or guaranteed.

This platform lives at `/platform` inside the `html-portfolio` repository
(it was built here because that was the only repository available to the
build session; consider moving it to its own repository before deploying
to production).

## Repository layout

```
platform/
  backend/     FastAPI + PostgreSQL + SQLAlchemy + Pandas/NumPy + XGBoost
  frontend/    Next.js + React + TypeScript + Tailwind CSS (added in Phase 12)
  docs/        (this file + SETUP/DATABASE/API/MODEL/BACKTEST/DEPLOYMENT)
```

## Build phases

The system is built incrementally. Each phase must pass its own tests
before the next begins.

| Phase | Scope | Status |
|---|---|---|
| 1 | Sportmonks API connection | **Done** |
| 2 | Database schema | Not started |
| 3 | Historical data ingestion | Not started |
| 4 | Feature engineering | Not started |
| 5 | Poisson baseline model | Not started |
| 6 | XGBoost model | Not started |
| 7 | Backtesting (walk-forward) | Not started |
| 8 | Probability calibration | Not started |
| 9 | Sportmonks model integration | Not started |
| 10 | Odds and market edge | Not started |
| 11 | Ranking engine | Not started |
| 12 | Dashboard (Next.js) | Not started |
| 13 | Automation (n8n) | Not started |

## Phase 1 — Sportmonks connection

**What was built**

- `backend/app/core/config.py` — a `Settings` object (pydantic-settings)
  that reads `SPORTMONKS_API_TOKEN` and related configuration exclusively
  from environment variables / a local, git-ignored `.env` file. The token
  is never hard-coded and instantiation fails loudly (a clear
  `ValidationError`) if it is missing or blank.
- `backend/app/integrations/sportmonks/client.py` — `SportmonksClient`, a
  resilient wrapper around the Sportmonks Football v3 API:
  - Exponential-backoff retries on network errors and `429`/`5xx`
    responses, honouring a `Retry-After` header when Sportmonks sends one.
  - `401`/`403` responses raise `SportmonksAuthError` immediately, without
    retrying (a bad token should fail fast, not burn the retry budget).
  - A client-side requests-per-minute budget (`_throttle`) that proactively
    paces requests instead of relying solely on reacting to `429`s.
  - Transparent pagination (`paginate()`) across Sportmonks' `data` /
    `pagination.has_more` response shape.
  - `test_connection()` plus thin endpoint helpers (`get_leagues`,
    `get_fixtures_between`, `get_fixture`) used to validate connectivity;
    more endpoints are added in later phases alongside the tables that
    store their data.
- `backend/app/main.py` — a minimal FastAPI app with `GET /health` and
  `GET /health/sportmonks`, the latter exercising a real (mockable) call
  through `SportmonksClient.test_connection()`.

**Tests** (`backend/tests/`, 15 tests, all passing)

- Configuration: missing/blank token raises validation error; token is
  correctly read from the environment; the source file contains no
  hard-coded token value.
- Client: token is sent only as a query parameter (never appears in the
  URL path); successful reads; pagination across multiple pages; auth
  errors fail without retrying; `429` retries then succeeds; `429`
  exhausted after max retries raises `SportmonksRateLimitError`; `5xx`
  retries then raises `SportmonksAPIError`; network errors retry then
  raise; plain `4xx` errors (e.g. `404`) raise without retrying;
  `test_connection()` succeeds/fails as expected.

All HTTP interactions in tests are mocked via `httpx.MockTransport` — no
real Sportmonks token or network access is required to run the suite, and
none is used.

Run them yourself:

```bash
cd platform/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then fill in SPORTMONKS_API_TOKEN for real use
python3 -m pytest -v
```

**Remaining risks / open items for later phases**

- No real Sportmonks token has been exercised against the live API in
  this session — the client's behaviour against real payload shapes
  (field names, included relations) should be spot-checked against a real
  token before Phase 3 (historical ingestion) begins.
- Sportmonks' actual rate-limit and pagination response shape should be
  double-checked against current API docs for the specific plan/token in
  use; the client's assumptions (`pagination.has_more`, `Retry-After` in
  seconds) are standard but plan-specific quirks are possible.
- No database, models, or endpoints beyond health checks exist yet — by
  design, per the phased build plan.

See `docs/SETUP.md` for environment setup instructions.
