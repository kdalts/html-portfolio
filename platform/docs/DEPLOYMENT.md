# Deployment

This document covers running the platform in production: what runs where,
how often, and how the pieces connect. See `docs/SETUP.md` for local
development setup and the manual step-by-step CLI walkthrough this
deployment guide automates.

## Overview

The platform has three deployable pieces:

| Piece | What it is | Suggested host |
|---|---|---|
| Backend API | FastAPI read-only service (`backend/app/main.py`) | Any container host (Fly.io, Render, a small VM) |
| Frontend dashboard | Next.js app (`frontend/`) | Vercel |
| Database | PostgreSQL 14+ | Supabase, or any managed PostgreSQL |
| Daily pipeline | `python -m app.automation.cli run` | A scheduler — n8n, cron, or a platform's own scheduled-job feature |

Nothing here requires all four to live in the same place. The API only
needs a `DATABASE_URL` it can reach; the pipeline only needs the same
`DATABASE_URL` plus `SPORTMONKS_API_TOKEN` and, if the daily report should
be delivered somewhere, `DAILY_REPORT_WEBHOOK_URL`.

## Database (Supabase or any PostgreSQL 14+)

1. Provision a PostgreSQL 14+ database (16 recommended — this schema uses
   `GENERATED ALWAYS AS ... STORED` columns, supported from PG 12+).
2. Set `DATABASE_URL` for the backend to a `postgresql+psycopg://...` URL.
3. Apply migrations from a machine that can reach the database:
   ```bash
   cd platform/backend
   export DATABASE_URL=postgresql+psycopg://...
   alembic upgrade head
   ```
4. See `docs/DATABASE.md` for the full schema and migration workflow.

Supabase specifically: use the pooled "Transaction" connection string for
the API's runtime connections and the direct connection string for
running `alembic upgrade head` (migrations need a session-level
connection, not a transaction-pooled one).

## Backend API (Vercel-adjacent container host)

The API is a standard ASGI app (`app.main:app`) — deploy it anywhere that
runs a long-lived Python process (Vercel's own runtime is not a fit for a
persistent ASGI server; Fly.io, Render, Railway, or a small VM all work).

```bash
cd platform/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Required environment variables: `DATABASE_URL`,
`CORS_ALLOWED_ORIGINS` (the deployed frontend's origin — never `*`). See
`docs/SETUP.md`'s environment variable table for the full list; every
value not listed there keeps a safe default.

Health checks: `GET /health` (process is up) and `GET /health/sportmonks`
(the Sportmonks token, if configured on this host, is valid) — point the
host's own health-check feature at `/health`.

## Frontend dashboard (Vercel)

```bash
cd platform/frontend
vercel deploy
```

Set the one required environment variable in the Vercel project:
`API_BASE_URL` → the deployed backend API's URL. Every page fetches with
`cache: "no-store"` and `export const dynamic = "force-dynamic"`
(documented in Phase 12), so no build-time revalidation configuration is
needed — the dashboard always reflects the database's current state.

## Daily pipeline (n8n, cron, or any scheduler)

`python -m app.automation.cli run [--date YYYY-MM-DD]` is the single
command a scheduler needs to invoke once per day, ahead of the earliest
kickoff it should cover. It runs every step documented in
`platform/README.md`'s Phase 13 section, isolates each step's failures so
one missing prerequisite (e.g. no trained ML artifact yet) doesn't stop
the rest of the run, and always attempts to send the daily report as its
last step.

Required environment: `DATABASE_URL`, `SPORTMONKS_API_TOKEN`, and the
Sportmonks reference IDs in `app/ingestion/sportmonks_reference.py` filled
in for a real subscription (placeholders until then — see Phase 3's
"Remaining risks"). Optional: `DAILY_REPORT_WEBHOOK_URL` (Slack incoming
webhook / Discord / n8n's own Webhook node / any JSON-accepting endpoint)
— if unset, the report is logged instead of delivered, which is a safe,
functional default, not a failure.

Exit code is `0` if every step succeeded, `1` if any step failed (check
the logged per-step detail to see which) — a scheduler should alert on a
non-zero exit.

### Option A: n8n

`automation/n8n-daily-pipeline.json` is an importable n8n workflow: a
Schedule Trigger (daily, before the earliest realistic kickoff — adjust
to the target leagues' timezones) followed by an Execute Command node
running `python -m app.automation.cli run`, with an IF node branching on
the exit code to a Slack/Discord/webhook notification node on failure.
Import it into n8n (Workflows → Import from File), point the Execute
Command node at the backend's deployment (a path on the same host, or an
SSH/Docker exec step if n8n runs elsewhere), and set the environment
variables above on whatever actually runs the command.

### Option B: plain cron

```
0 6 * * * cd /path/to/platform/backend && /path/to/.venv/bin/python -m app.automation.cli run >> /var/log/football-pipeline.log 2>&1
```

Model training (Phase 6), backtesting (Phase 7), and league-reliability
scoring (Phase 11) are **not** part of the daily pipeline by design — they
are periodic/on-demand jobs, not something that needs to re-run every
day. Schedule them separately (e.g. weekly/monthly) or run them manually
via their own CLIs (`docs/SETUP.md` steps 9–14) as enough new results
accumulate to justify retraining.

## What's still a manual/on-demand step

- Initial historical ingestion (`app.ingestion.cli fixtures`) — a one-time
  backfill, not something the daily pipeline repeats.
- Retraining the XGBoost model (`app.models.ml_cli train`) and re-fitting
  the ensemble/calibration (`app.models.ensemble_cli fit`) — periodic, on
  a cadence the operator chooses based on how much new results accumulate.
- Re-running the walk-forward backtest and league-reliability aggregation
  (`app.backtest.cli run`, `app.ranking.cli league-reliability`) — the
  same cadence question, and a prerequisite before trusting a newly
  added league's `daily` ranking output.

## Remaining risks

- No real deployment has been exercised in this session (no hosting
  account, no live Sportmonks token) — the steps above follow each
  platform's documented conventions but are unverified against a live
  deployment.
- The n8n workflow template is a starting point (schedule + run + notify
  on failure) — a real deployment should also monitor for the pipeline
  simply not firing (a scheduler outage), which is outside what the
  workflow itself can detect.
