# Frontend — Football Over 2.5 Platform Dashboard

Next.js (App Router) + React + TypeScript + Tailwind CSS. Six pages, all
server-rendered on every request (`export const dynamic = "force-dynamic"`)
since the data — daily rankings, model performance, backtest results —
changes as often as the backend CLI pipelines run; nothing here should be
served from a stale build-time or ISR snapshot.

## Pages

| Route | Page |
|---|---|
| `/` | Today's Top 10 |
| `/matches/[fixtureId]` | Match Detail |
| `/leagues` | League Performance |
| `/models` | Model Performance |
| `/backtest` | Historical Backtest |
| `/system` | System Health |

## Setup

```bash
npm install
cp .env.example .env.local   # set API_BASE_URL to your backend
npm run dev
```

Requires the backend API running (see `../backend/`'s `docs/SETUP.md`)
and populated with at least some data (fixtures/features/predictions/
rankings) for the pages to show anything beyond their empty states.

## Architecture notes

- `src/lib/api.ts` — the only place that talks to the backend. Every
  call passes `cache: "no-store"`. `API_BASE_URL` is read server-side
  only (no `NEXT_PUBLIC_` prefix) — the backend's location, and
  everything the backend itself keeps secret (`SPORTMONKS_API_TOKEN`,
  `DATABASE_URL`), never reaches client-side JavaScript. Every page here
  is also a Server Component, so there is no client-side fetch path to
  audit for that in the first place.
- `src/lib/types.ts` — hand-written TypeScript mirrors of
  `backend/app/api/schemas.py`'s Pydantic response models.
- `src/components/ui.tsx` — shared visual primitives, including
  `ProbabilityPill`/`ConfidencePill`/`EdgePill`, deliberately distinct
  colors (blue/violet/green-or-red) for the platform's three
  never-conflated quantities: probability, confidence, and market edge.
- Every page renders a footer disclaimer ("Predictions are probability
  estimates, not guarantees...") — the platform's core rule that nothing
  here claims certainty.

## Verification

Typecheck, lint, and build are all clean (`npx tsc --noEmit`, `npm run
lint`, `npm run build`). Beyond that, this was checked against a live
backend, not just compiled: the backend and this dev server were both
run locally against a seeded PostgreSQL database, and every page's
rendered HTML was confirmed (via curl) to contain the actual seeded
values — team names, probabilities, league reliability scores,
backtest/calibration numbers — not just placeholder markup. The empty
state (a date with no ranking) and the 404 state (an unknown fixture)
were checked the same way.
