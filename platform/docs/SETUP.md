# Setup

This document currently covers Phase 1 (Sportmonks connection) setup. It
will be extended as later phases add the database, models, and frontend.

## Prerequisites

- Python 3.11+
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

## 3. Run the tests

```bash
cd platform/backend
python3 -m pytest -v
```

These tests mock all HTTP calls (`httpx.MockTransport`) and do not require
a real token or network access.

## 4. Run the API locally

```bash
cd platform/backend
uvicorn app.main:app --reload
```

Then check:

- `GET http://localhost:8000/health` → `{"status": "ok"}`
- `GET http://localhost:8000/health/sportmonks` → `{"status": "ok", "provider": "sportmonks"}`
  if `SPORTMONKS_API_TOKEN` is set and valid, or a `502`/`503` with a
  descriptive error otherwise.

## Environment variables (Phase 1)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SPORTMONKS_API_TOKEN` | Yes | — | Sportmonks Football API token |
| `SPORTMONKS_BASE_URL` | No | `https://api.sportmonks.com/v3/football` | API base URL |
| `SPORTMONKS_TIMEOUT_SECONDS` | No | `15` | Per-request HTTP timeout |
| `SPORTMONKS_MAX_RETRIES` | No | `5` | Retries for transient failures |
| `SPORTMONKS_BACKOFF_BASE_SECONDS` | No | `1.0` | Base for exponential backoff |
| `SPORTMONKS_REQUESTS_PER_MINUTE` | No | `60` | Client-side throttle budget |

Further phases will add `DATABASE_URL` and other variables, documented
here as they are introduced.
