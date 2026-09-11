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
  frontend/    Next.js + React + TypeScript + Tailwind CSS (Phase 12)
  automation/  n8n workflow template (Phase 13)
  docs/        SETUP/DATABASE/API/MODEL/BACKTEST/DEPLOYMENT
```

## Build phases

The system is built incrementally. Each phase must pass its own tests
before the next begins.

| Phase | Scope | Status |
|---|---|---|
| 1 | Sportmonks API connection | **Done** |
| 2 | Database schema | **Done** |
| 3 | Historical data ingestion | **Done** |
| 4 | Feature engineering | **Done** |
| 5 | Poisson baseline model | **Done** |
| 6 | XGBoost model | **Done** |
| 7 | Backtesting (walk-forward) | **Done** |
| 8 | Ensemble + probability calibration | **Done** |
| 9 | Sportmonks model integration | **Done** |
| 10 | Odds and market edge | **Done** |
| 11 | Ranking engine | **Done** |
| 12 | Dashboard (Next.js) | **Done** |
| 13 | Automation (n8n) | **Done** |
| 14 | 15-point checklist | **Done** |

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

## Phase 2 — Database schema

**What was built**

- All 14 required tables (`leagues`, `teams`, `seasons`, `fixtures`,
  `match_statistics`, `match_xg`, `sportmonks_predictions`, `odds`,
  `team_features`, `match_features`, `model_predictions`,
  `backtest_results`, `league_model_performance`, `daily_rankings`) as
  SQLAlchemy 2.0 models under `backend/app/db/models/`, every one with a
  primary key, foreign keys with deliberate delete semantics (RESTRICT for
  reference data, CASCADE for anything derived from a fixture), indexes,
  and `created_at`/`updated_at` timestamps.
- `fixtures.total_goals` and `fixtures.over_2_5` are PostgreSQL
  `GENERATED ALWAYS AS ... STORED` columns computed only from
  `home_goals`/`away_goals` — the Over 2.5 target label is enforced by the
  database itself and cannot drift from `home_goals + away_goals >= 3`, and
  is `NULL` for any unfinished fixture. `odds`' implied probabilities, its
  de-vigged `market_probability`, and `model_predictions.edge`
  (`final_probability - market_probability`) are generated columns for the
  same reason: derived values can't disagree with their inputs.
- `team_features` (rolling pre-match form per team per fixture, in both
  "overall" and venue-specific variants, for 3/5/10-match windows across
  10 stats) is built programmatically — 66 columns generated from a
  `(stat x window x context)` spec rather than hand-typed, with a matching
  test that verifies completeness.
- Alembic is configured (`backend/alembic/`) with the connection string
  injected from `Settings`/`DATABASE_URL` at runtime — never hard-coded in
  `alembic.ini`. The initial migration was generated, applied to a real
  local PostgreSQL 16 database, verified reversible (`downgrade base` then
  `upgrade head` recreates all 15 tables including `alembic_version`), and
  `alembic check` confirms the models and migration are in sync.
- Full schema documentation: `docs/DATABASE.md`.

**Tests** (`backend/tests/`, 47 tests total — 32 new in this phase, all passing)

- `test_db_schema.py` (structural, no DB required): all 14 required tables
  present and no extras; every table has a primary key and timestamps;
  cascade-vs-restrict FK rules match the intended data lifecycle;
  `team_features`' generated column set is complete; `model_predictions`
  genuinely keeps probability, confidence, and edge as distinct columns.
- `test_db_integration.py` (against a real local PostgreSQL database,
  skips cleanly if unreachable): the Over 2.5 label is verified correct
  for every goal combination tested, including that a fixture with only
  one final score recorded resolves to `NULL`, never a false 0/1; CHECK
  constraints reject invalid status, negative goals, and same-team
  fixtures; FK constraints reject a fixture referencing a nonexistent
  league; unique constraints reject duplicate `team_features` rows and
  duplicate ranks on the same day; the `odds` de-vig math and
  `model_predictions.edge` generated columns are checked against
  independently computed expected values; deleting a fixture cascades to
  its `match_statistics` row; deleting a team referenced by a fixture is
  correctly blocked.

Run them yourself (requires a local PostgreSQL instance):

```bash
cd platform/backend
createdb football_platform_test
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test
python3 -m pytest -v
```

**Remaining risks / open items for later phases**

- The schema was designed from the spec's table list and column
  requirements, not from real Sportmonks payloads — field names/shapes
  should be cross-checked against real API responses during Phase 3
  (ingestion), and the schema may need minor adjustment then.
- The pre-kickoff leakage guard for `sportmonks_predictions.retrieved_at`,
  `odds.retrieved_at`, and `model_predictions.predicted_at` is documented
  but *not* enforced by a database constraint (Postgres CHECK constraints
  can't reference another table). It must be enforced in application code
  from Phase 3 onward and is a prime candidate for its own leakage-guard
  tests, as the spec requires.
- `team_features`/`match_features` schemas encode this phase's judgment
  call about which rolling stats and windows matter; Phase 4 (feature
  engineering) may reveal a need to add columns (a new migration), not
  redesign the table shape.
- No seed/reference data has been loaded yet — tables are empty until
  Phase 3.

## Phase 3 — Historical data ingestion

**What was built**

- `backend/app/ingestion/leakage.py` — `ensure_not_leaked(observed_at,
  kickoff, label=...)`, the single enforcement point for the platform's
  core leakage rule. Strict: `observed_at` must be *before* (not `<=`)
  `kickoff`, and both timestamps must be timezone-aware, so a naive
  datetime can never silently slip through a comparison.
- `backend/app/ingestion/mappers.py` — pure functions turning raw
  Sportmonks fixture JSON into the column dicts the schema expects
  (`map_league`, `map_team`, `map_season`, `map_fixture`,
  `map_match_statistics`, `map_match_xg`, `map_sportmonks_prediction`,
  `map_odds`). No I/O; every function takes a dict in and returns a
  dict/list out, which is what makes them cheap to test exhaustively with
  canned payloads.
- `backend/app/ingestion/repository.py` — idempotent
  `INSERT ... ON CONFLICT DO UPDATE` upserts for every ingested table.
  Re-running ingestion over the same data never creates duplicates; rows
  are matched on their natural/unique key and updated in place. The
  `sportmonks_predictions` and `odds` upserts call `ensure_not_leaked`
  before writing anything — this is where the guard documented as an
  application-layer responsibility in Phase 2 actually gets enforced.
- `backend/app/ingestion/service.py` — orchestration
  (`ingest_leagues`, `ingest_fixtures_between`,
  `ingest_prediction_for_fixture`, `ingest_odds_for_fixture`). Each
  fixture/league is processed inside its own SAVEPOINT
  (`session.begin_nested()`), so one malformed record is skipped and
  recorded in the returned `IngestionSummary` (`fetched` / `upserted` /
  `failed` / `errors`) without rolling back — or blocking — everything
  else in the same batch.
- `backend/app/ingestion/cli.py` — a runnable entry point:
  `python -m app.ingestion.cli leagues` and
  `python -m app.ingestion.cli fixtures --start ... --end ...`.
- `backend/app/ingestion/sportmonks_reference.py` — the Sportmonks
  `type_id`/`market_id` constants needed to interpret statistics,
  predictions, and odds. **These are placeholders (`None`)** — see
  "Remaining risks" below.

**A deliberate design decision: historical backfill never touches
`sportmonks_predictions` or `odds`.** `ingest_fixtures_between` populates
`leagues`/`teams`/`seasons`/`fixtures` and, optionally, `match_statistics`/
`match_xg` — all purely factual, post-match data with no leakage
exposure (they describe what already happened, and are only ever
consumed later as historical inputs to *future* predictions). Sportmonks'
own predictions and bookmaker odds are different: for a fixture played
long ago, there is no way to know whether calling the API for it *today*
returns values that reflect what was knowable before that fixture's
kickoff. Rather than guess, bulk historical backfill simply never writes
to those two tables. `ingest_prediction_for_fixture` /
`ingest_odds_for_fixture` exist instead for the operational, near-kickoff
case (to be wired into Phase 13 automation), and every write through them
passes `ensure_not_leaked`.

**Tests** (`backend/tests/`, 95 tests total — 48 new in this phase, all passing)

- `test_leakage_guard.py` — pure: allows strictly-pre-kickoff timestamps;
  rejects exactly-at-kickoff, post-kickoff (including the realistic
  "pulled months after the match" case), naive datetimes on either side,
  and missing timestamps; checks the error message names both timestamps.
- `test_ingestion_mappers.py` — pure, canned Sportmonks-shaped JSON:
  status-code translation and fallback; kickoff parsing (timestamp
  preferred, string fallback, missing/unparseable rejected); fixture
  mapping for finished and upcoming matches, and for malformed payloads
  (missing participants/ids); league/team/season mapping; statistics/xG
  extraction (including "unconfigured type_id degrades to empty, not an
  error"); prediction extraction and percent-to-probability conversion;
  odds Over/Under pairing per bookmaker, line filtering, and incomplete
  pairs being dropped.
- `test_ingestion_repository.py` — real PostgreSQL: every upsert is
  proven idempotent (re-upsert updates in place, never duplicates,
  including through the fixture's generated `total_goals`/`over_2_5`
  columns); `sportmonks_predictions`/`odds` upserts succeed pre-kickoff
  and are refused (with nothing written) post-kickoff.
- `test_ingestion_service.py` — mocked Sportmonks HTTP (`httpx.MockTransport`,
  same pattern as Phase 1) against a real database: league/fixture
  ingestion is idempotent end-to-end; statistics/xG ingestion populates
  the right rows; **a batch with one malformed fixture still ingests every
  other fixture in that batch**, with the failure recorded in the
  summary rather than aborting the run; `ingest_prediction_for_fixture`
  accepts a pre-kickoff retrieval and rejects a post-kickoff one.

Run them yourself (requires a local PostgreSQL instance):

```bash
cd platform/backend
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test
python3 -m pytest -v
```

**Remaining risks / open items for later phases**

- `sportmonks_reference.py`'s type/market IDs are placeholders
  (`None`). The mapping *mechanism* is fully implemented and tested
  against arbitrary IDs, but match_statistics/match_xg/
  sportmonks_predictions/odds will extract nothing until the real IDs for
  your Sportmonks subscription are filled in (from its `/core/types` and
  `/odds/markets` reference endpoints).
- Payload shape assumptions (documented at the top of `mappers.py`) are
  standard Sportmonks v3 conventions but still unverified against a live
  token — same risk flagged in Phase 1/2, now more consequential since
  ingestion code actively depends on the exact field names.
  `map_fixture`/`map_league`/etc. raising `MappingError` on an unexpected
  shape (rather than silently producing wrong data) is the safety net for
  this until it's checked.
- "Failed-job tracking" is currently an in-memory `IngestionSummary`
  (counts + error strings) returned to the caller and logged — not a
  persisted table (a `job_runs`-style table isn't in the required schema
  list). For unattended scheduled runs (Phase 13), this summary will need
  to be captured somewhere durable (log aggregation, or a table added
  then if needed).
- No leagues/fixtures have actually been pulled from the live API in this
  session (no real Sportmonks token available). Everything above is
  verified against a real PostgreSQL database and mocked HTTP responses,
  not a real Sportmonks account.

## Phase 4 — Feature engineering

**What was built**

- `backend/app/common/` — a small refactor extracted from Phase 3 so this
  phase could reuse it cleanly: `batch.py` (`BatchSummary`, the
  fetched/upserted/failed/errors result every batch pipeline now returns)
  and `upsert.py` (the generic `INSERT ... ON CONFLICT DO UPDATE` helper).
  `app/ingestion/` was updated to use these instead of its own copies —
  same behavior, no duplicated logic between ingestion and features.
- `backend/app/features/team_match_log.py` — `fetch_team_appearances`
  turns a team's fixtures (home and away) into a flat list of
  "appearances", each carrying its own `kickoff`, this team's goals/xG/
  stats as "for" and the opponent's as "against". This "long" shape is
  what makes rolling-window computation simple: it's just "filter to
  `kickoff < before`, take the most recent N".
- `backend/app/features/rolling.py` — pure, DB-free rolling-window
  computation. This is where the leakage boundary is enforced, once, for
  every stat: `compute_rolling_stats` only considers appearances with
  `kickoff < before` (strictly before). Since a fixture's own kickoff is
  never less than itself, asking for a fixture's features with
  `before=fixture.kickoff` can never include that fixture's own result —
  even for a fixture that has already been played, which is exactly what
  backtesting needs. Produces all 66 `team_features` columns (10 stats ×
  3 windows × overall/venue-specific), generated from the same
  `STAT_KEYS`/`ROLLING_WINDOWS`/`FEATURE_CONTEXTS` constants the Phase 2
  schema uses, with an import-time assertion that the stat-accessor table
  can never silently drift from `STAT_KEYS`.
- `backend/app/features/league_features.py` / `h2h_features.py` — league
  scoring-environment context (scoped to the fixture's own season, since
  scoring environments shift year to year) and head-to-head history
  (gated behind a minimum sample size — `MIN_H2H_MATCHES = 2` — per the
  spec's "where sufficient historical data exists"), both using the same
  strict `kickoff < before` cutoff.
- `backend/app/features/service.py` — `compute_features_for_fixture`
  (one fixture → home/away `team_features` rows + one `match_features`
  row) and `compute_and_store_features_for_fixtures` (the batch driver,
  same per-item SAVEPOINT + `BatchSummary` error-isolation pattern as
  ingestion). Works for fixtures of **any** status — an upcoming fixture
  needs features computed for it (for the daily ranking) exactly as much
  as a historical one does (for training), and both get them from the
  same code path with no special-casing.
- `backend/app/features/cli.py` — `python -m app.features.cli build
  --start ... --end ...`.

**Tests** (`backend/tests/`, 126 tests total — 31 new in this phase, all passing)

- `test_rolling_features.py` (pure, no DB) — the leakage boundary itself:
  an appearance exactly at the cutoff is excluded, one strictly before is
  included, and appearances *after* the cutoff (a team's later matches,
  already in the DB) never leak in. Also: exact-window averaging, taking
  only the most recent N when more history exists, fewer-than-window
  handling, a stat that's missing on every match in the window resolving
  to `None` (not `0.0`), partial-missing values averaging only what's
  present, BTTS/Over-2.5 percentage correctness, venue-context filtering,
  and that the generated column set exactly matches the Phase 2 schema.
- `test_league_h2h_features.py` (real PostgreSQL) — league averages
  computed correctly and season-scoped; a match exactly at the cutoff
  excluded; h2h below/at the minimum-sample threshold; both venue orders
  of a matchup counted as the same head-to-head history; unrelated
  matchups correctly excluded.
- `test_features_service.py` (real PostgreSQL) — **the single most
  important test in this phase**,
  `test_a_fixtures_own_result_never_leaks_into_its_own_features`: a
  fixture is marked `FT` with a score recorded, and computing *that same
  fixture's* features is proven to use only the three matches before it,
  never its own result. Also: home/away appearance extraction and xG
  for/against joins are correct; matches without a recorded result are
  excluded from a team's history; an upcoming (`NS`) fixture still gets
  full features from prior history; league/h2h values flow through into
  `match_features`; the batch driver persists rows, is idempotent, and
  isolates one bad fixture from the rest of the batch.
- Manually verified end-to-end against a real (non-test) database outside
  the pytest transaction-rollback harness: seeded a small league/three
  teams/two fixtures, ran `compute_and_store_features_for_fixtures`, and
  confirmed the stored `team_features`/`match_features` rows matched the
  expected values by hand.

Run them yourself (requires a local PostgreSQL instance):

```bash
cd platform/backend
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test
python3 -m pytest -v
```

**Remaining risks / open items for later phases**

- Box-score stats (`shots`, `shots_on_target`, `big_chances`, `corners`)
  and `xg`/`xga` will be `None` in every `team_features` row until Phase
  3's `sportmonks_reference.py` type IDs are configured with real values
  — the goals-based stats (`goals_scored`, `goals_conceded`, `btts_pct`,
  `over_2_5_pct`) don't depend on that and are already fully correct.
- `data_completeness_score` (on `match_features`) is a simple, explicitly
  documented placeholder heuristic (how much of the last-10-match window
  is filled in, averaged across both teams). Phase 11 (ranking/
  confidence) may want something more sophisticated; this is a reasonable
  default in the meantime, not a final design.
- League features are scoped to the fixture's own season by design — this
  means early-season fixtures have a small `league_sample_size` (honestly
  reported, not hidden). No cross-season blending or shrinkage is applied;
  that's a modeling decision left to Phase 5/6 if needed, not a Phase 4
  concern.
- `fetch_team_appearances` loads a team's entire history unbounded (no
  pagination/limit) — correct, but a known scaling consideration for
  leagues with many years of data once ingestion volume grows.

## Phase 5 — Poisson baseline model

**What was built**

- `backend/app/models/poisson.py` — pure math, no DB: the classic
  independent-Poisson attack/defense-strength model.
  `expected_home_goals`/`expected_away_goals` are derived from each
  team's venue-specific scoring/conceding rate (Phase 4's
  `venue_last{W}_goals_scored`/`_conceded`, falling back to
  `overall_last{W}_*` if a team has no venue-specific history yet)
  normalized against the league's home/away goal averages
  (`match_features.league_home_goals_avg`/`league_away_goals_avg`). The
  module docstring spells out, explicitly, which league average each
  defense ratio normalizes against — `away_defense` against `mu_home`,
  `home_defense` against `mu_away` — because a team's away-conceded
  total is drawn from the same league-wide distribution as home teams'
  scoring, not away teams'. Getting this backwards is a classic bug in
  these models, and `test_estimate_poisson_defense_normalized_against_opposite_league_average`
  exists specifically to catch it via deliberately asymmetric inputs.
  `poisson_over_2_5_probability(lambda_total)` is `1 - exp(-λ)(1+λ+λ²/2)`,
  i.e. `P(X>=3)` for `X ~ Poisson(λ_total)` — valid because the sum of two
  independent Poisson variables is itself Poisson with the summed rate.
  Returns `None` (never a fabricated number) whenever the league baseline
  or a team's goal rate isn't available.
- `backend/app/models/poisson_service.py` — reads a fixture's
  `team_features`/`match_features` rows, computes the estimate, and
  upserts `expected_home_goals`/`expected_away_goals`/`poisson_probability`
  onto `model_predictions`. **Deliberately does not apply the
  ensure_not_leaked guard** used for `sportmonks_predictions`/`odds` —
  documented in the module docstring: this model's only inputs are
  Phase 4 features, which already guarantee pre-kickoff-only data by
  construction, so running the computation today for a 2020 fixture
  yields the exact same number a genuine 2020 pre-match run would have.
  `predicted_at` records when the computation ran, not a claim about data
  availability.
- Every phase from here on writing to `model_predictions` shares one
  `model_version` (`app/models/constants.py:DEFAULT_MODEL_VERSION`), so
  Poisson/ML/ensemble/calibration all land on the *same* row per fixture
  instead of each creating their own — verified by a test that seeds an
  `ml_probability` on a row and confirms the Poisson upsert fills in
  `poisson_probability` alongside it without touching the existing value.
- `backend/app/models/poisson_cli.py` — `python -m app.models.poisson_cli
  build --start ... --end ...`.

**Tests** (`backend/tests/`, 146 total — 20 new, all passing)

- `test_poisson_model.py` (pure): the Poisson CDF formula against a
  textbook reference value (λ=2 → P(Over 2.5) ≈ 0.323324); monotonicity;
  bounds; negative-λ rejection; the attack/defense formula against
  hand-calculated expected goals; the defense-normalization regression
  guard described above; venue→overall fallback; `None` returned for
  missing/zero league averages and for a team with no history at all;
  window parameter correctness.
- `test_poisson_service.py` (real PostgreSQL): correct end-to-end values
  from seeded features; `None`/skipped when features aren't computed yet;
  the batch driver persists, is idempotent, and merges into (never
  clobbers) a `model_predictions` row another phase already wrote to;
  one fixture missing features doesn't abort the batch.

**Remaining risks**

- Accuracy is only as good as Phase 4's rolling stats, which are
  currently goals-only in practice (box-score stats/xG await Phase 3's
  placeholder type IDs) — the Poisson model as built only needs goals
  data, so it's unaffected, but it means this baseline can't yet be
  cross-checked against an xG-based expected-goals sanity check.
  `window` defaults to 10 matches; no tuning of window size against
  held-out data has been done yet — that's what Phase 7 backtesting is for.

## Phase 6 — XGBoost model

**What was built**

- `backend/app/models/dataset.py` — assembles one training row per
  finished fixture: the home team's `team_features` columns prefixed
  `home_`, the away team's prefixed `away_`, `match_features`' league/h2h
  columns as-is, plus `fixture_id`/`kickoff`/`league_id`/`over_2_5`
  (`META_COLUMNS`, excluded from the feature set). `build_feature_row_for_fixture`
  does the same for a single fixture without requiring a known result —
  used at prediction time for upcoming fixtures.
- `backend/app/models/chronological_split.py` — splits a DataFrame into
  train/val/test purely by kickoff cutoffs. No shuffling step exists to
  get wrong: filtering by date inherently preserves time order. Per spec
  ("never randomly shuffle historical matches across time"), this is the
  only splitting mechanism used anywhere in training.
- `backend/app/models/xgboost_model.py` — a thin, DB-free wrapper around
  `xgboost.train`: `binary:logistic` objective, trains only on the train
  partition, uses the validation partition solely for early stopping/
  reporting (never gradient updates — the held-out test evaluation is
  Phase 7's backtesting, not this). Missing feature values (expected in
  practice — box-score stats/xG stay `None` until Phase 3's placeholder
  type IDs are configured, and early-season rolling windows are
  naturally incomplete) go straight to XGBoost's native missing-value
  handling rather than being imputed.
- `backend/app/models/ml_service.py` — `train_and_save_model` writes a
  self-describing filesystem artifact (native XGBoost JSON + a metadata
  sidecar recording feature-column order, training window, and
  validation metrics — there's no "trained model" table in the required
  schema, so this is the standard alternative). `compute_and_store_ml_predictions`
  loads it once per batch and writes `ml_probability` onto
  `model_predictions`, merging into the same row Phase 5's Poisson
  prediction already wrote to (same `DEFAULT_MODEL_VERSION` mechanism).
- `backend/app/models/ml_cli.py` — `python -m app.models.ml_cli train
  --train-start ... --train-end ... --val-end ...` and `... predict
  --start ... --end ...`.
- Added `pandas`, `numpy`, `scikit-learn`, `xgboost` to `requirements.txt`.
  Trained model artifacts (`backend/artifacts/`) are git-ignored — any
  model trained in this sandbox would only reflect synthetic test data,
  so committing one would be actively misleading; operators train their
  own after real historical ingestion.

**Tests** (`backend/tests/`, 171 total — 25 new, all passing)

- `test_chronological_split.py` (pure): correct partitioning by cutoff,
  no overlap/gaps, rows sorted (never left in arbitrary/random order)
  within each partition, boundary dates resolve to the right side.
- `test_xgboost_model.py` (real XGBoost training on synthetic data, no
  DB): **the model actually learns** — trained on a feature that
  near-perfectly determines the label, it predicts confidently and
  correctly on clear cases (not just "runs without crashing"); missing
  values don't crash prediction; save/load round-trips to identical
  predictions.
- `test_ml_dataset.py` (real PostgreSQL): only finished fixtures with
  computed features are included; column prefixing is correct with no
  raw/unprefixed or ORM-bookkeeping columns leaking through; date-range
  and chronological-ordering correctness; an upcoming fixture still gets
  a feature row (no target key) for prediction.
- `test_ml_service.py` (real PostgreSQL + a real small training run):
  end-to-end train → save artifact → load → predict, using a synthetic
  but genuinely learnable relationship seeded into `team_features`;
  empty training window raises clearly; predicting with no trained
  artifact raises clearly (not a silent wrong answer); a prediction
  merges into an existing Poisson row without clobbering it; a fixture
  missing features is skipped and recorded as a batch failure.

**Remaining risks**

- No hyperparameter tuning has been done — `DEFAULT_PARAMS` in
  `xgboost_model.py` are reasonable, conservative defaults (shallow
  trees, low learning rate, subsampling), not the product of a search.
  Phase 7's backtesting is what should inform whether they need
  revisiting.
- Feature quality is bounded by Phase 4/3 as already noted: box-score
  stats/xG are `None` everywhere until real Sportmonks type IDs are
  configured, so in practice the model currently trains on goals-based
  features only.
- No real historical data has been ingested in this session (no live
  Sportmonks token), so no real model has actually been trained —
  everything above is verified against synthetic data with a known,
  controlled relationship to the label.

## Phase 7 — Backtesting (walk-forward)

**What was built** — see `docs/BACKTEST.md` for the full design writeup
(methodology, metric definitions, the home/away segment's interpretation).
Summary:

- `backend/app/backtest/metrics.py` — Log Loss, Brier Score, ROC-AUC,
  Accuracy, Precision, Recall, a probability-band-based Calibration
  Error, and Hit Rate (deliberately distinct from Precision — see
  `docs/BACKTEST.md`). Every function returns `None`, never a fabricated
  number, when undefined (zero samples, single class).
- `backend/app/backtest/probability_bands.py` — bins a probability into
  the schema's `PROBABILITY_BANDS` (imported, not redefined).
- `backend/app/backtest/segments.py` — turns per-fixture evaluation rows
  into `backtest_results` rows sliced by league, season, probability
  band, and home/away, plus an overall row; empty segments are omitted.
- `backend/app/backtest/walkforward.py` — the expanding-window folds from
  the spec's own example (train 2019–2022→test 2023, 2019–2023→test 2024,
  2019–2024→test 2025). Poisson needs no retraining per fold (Phase 4's
  features are already leakage-safe); **ML trains a fresh model per fold
  using only that fold's own training window**, proven directly by a test
  that reads the saved artifact's metadata and confirms its training
  cutoff never reaches the fold's test period.
- `backend/app/backtest/cli.py` — `python -m app.backtest.cli run`.

**Tests** (`backend/tests/`, 208 total — 37 new, all passing)

- `test_backtest_metrics.py` / `test_probability_bands.py` /
  `test_backtest_segments.py` (pure): every metric against a
  hand-computed value; zero-division handled cleanly (0.0, not a
  warning/NaN); Hit Rate proven numerically distinct from Precision;
  band boundaries; segment grouping and omission-when-empty.
- `test_backtest_walkforward.py` (real PostgreSQL + real per-fold
  training): results written for every configured model_type and every
  segment type; **the central leakage guarantee — the ML artifact's own
  metadata proves its training window never reaches the fold's test
  period**; idempotent re-run; an empty fold produces no rows without
  erroring.

**Remaining risks** — no real historical data ingested yet, so no real
backtest has actually been run; `sportmonks`/`raw_ensemble`/`final`
model_types aren't evaluated here (they don't exist until Phases 8–9) but
`run_walkforward_backtest`'s `model_types` parameter is built to extend
to them without changes to this phase's code.

## Phase 8 — Ensemble + probability calibration

The spec's ENSEMBLE section (combine poisson/ml/sportmonks probabilities,
weights fit on validation data, never fixed) and CALIBRATION section
(Platt vs. Isotonic, selected on validation data) are bundled into one
phase, since they're the same two-step pipeline: `raw_ensemble_probability`
→ `final_probability`. See `docs/MODEL.md` for the full writeup.

**What was built**

- `backend/app/models/ensemble.py` — fits non-negative weights (summing
  to 1) over whichever of `poisson_probability`/`ml_probability`/
  `sportmonks_probability` have ≥80% coverage in the validation set,
  minimizing validation log loss. A source below that coverage threshold
  gets weight `0.0` — **never guessed** — which is exactly
  `sportmonks_probability`'s state until Phase 9 populates it; re-fitting
  later is how it earns a real weight. Applying the weights to a specific
  row renormalizes over whatever sources are actually present on it, so
  one missing source doesn't silently shrink the ensemble.
- `backend/app/models/calibration.py` — fits both Platt scaling and
  Isotonic regression on validation data and keeps whichever achieves
  lower validation log loss — the method itself is data-driven, not
  assumed. Both are serialized as small, self-contained parameter sets
  (a sigmoid's `(coef, intercept)`; Isotonic's breakpoint arrays) rather
  than pickled sklearn objects, so applying a saved calibrator later
  never depends on sklearn or matching library versions.
- `backend/app/models/ensemble_service.py` — `fit_ensemble_and_calibration`
  reads already-stored `model_predictions` rows for a validation window,
  fits both steps, and saves a JSON artifact (same filesystem-artifact
  pattern as Phase 6). `apply_ensemble_and_calibration_for_fixtures`
  writes `raw_ensemble_probability`/`ensemble_weights`/
  `calibration_method`/`final_probability` onto the fixture's existing
  `model_predictions` row, carrying forward its `predicted_at` rather
  than refreshing it — see the caught-and-fixed bug below.
- `backend/app/models/ensemble_cli.py` — `python -m app.models.ensemble_cli
  fit|apply`.

**A real bug this phase's tests caught:** the first version of
`apply_ensemble_and_calibration_for_fixtures` upserted only the four new
columns, omitting `predicted_at`. PostgreSQL validates NOT NULL columns
against the *proposed* `INSERT` row even when `ON CONFLICT DO UPDATE`
ends up running instead of the insert — so this failed with a
`NotNullViolation` on every fixture, despite the row already existing
with `predicted_at` set. Fixed by carrying the existing row's
`predicted_at` forward into the upsert, which also happens to be the
semantically correct choice (adding ensemble/calibration columns to a row
shouldn't change "when this fixture's prediction was generated").

**Tests** (`backend/tests/`, 231 total — 23 new, all passing)

- `test_ensemble.py` (pure): weights sum to 1 over available sources; an
  entirely-missing source gets exactly `0.0`, never a guess; an
  informative source outweighs a noise source; below/above the coverage
  threshold; per-row renormalization when a source is missing on that
  specific row.
- `test_calibration.py` (pure): falls back to `"none"` with too little
  data or a single class; **calibration measurably improves log loss**
  on a deliberately overconfident synthetic dataset (not just "runs");
  both calibrators round-trip through their serialized dict form to
  identical outputs; Isotonic's output is monotonic; outputs stay in
  `[0, 1]`.
- `test_ensemble_service.py` (real PostgreSQL): fitting produces a
  correct artifact; raises clearly with no validation data or an unfitted
  config; applying preserves the existing `poisson_probability` while
  adding the new columns (this is the test that caught the bug above); a
  fixture with no stored prediction is skipped and recorded; a final
  sanity check that `final_probability` flows correctly into Phase 2's
  generated `edge` column once market data is present.

**Remaining risks**

- `sportmonks_probability` has zero weight everywhere right now — Phase 9
  hasn't populated it yet. The mechanism is ready; nothing here needs to
  change once it is, only a re-fit.
- The 0.70 confidence threshold implicit in Phase 7's Hit Rate metric and
  the ensemble's coverage threshold (0.80) are reasonable defaults, not
  tuned against real outcomes — there is no real historical data in this
  session to tune them against.

## Phase 9 — Sportmonks model integration

The heavy lifting was already done in Phase 3: `ingest_prediction_for_fixture`
retrieves and stores Sportmonks' own Over 2.5 probability in
`sportmonks_predictions`, enforcing the leakage guard
(`retrieved_at < kickoff`) at ingestion time. A row only ever exists there
because it already passed that check — so this phase adds no new leakage
surface. Phase 9's job is narrower: sync it into the unified
`model_predictions` row Phase 8's ensemble reads from.

**What was built**

- `backend/app/models/sportmonks_service.py` —
  `sync_sportmonks_prediction_for_fixture` copies
  `sportmonks_predictions.over_2_5_probability` onto
  `model_predictions.sportmonks_probability`, carrying forward the
  existing row's `predicted_at` (same fix Phase 8 needed — Postgres
  validates NOT NULL columns against the proposed INSERT row even under
  `ON CONFLICT DO UPDATE`). `sync_and_store_sportmonks_predictions` is
  the usual per-item-isolated batch driver.
- `backend/app/models/sportmonks_cli.py` — `python -m
  app.models.sportmonks_cli sync --start ... --end ...`.
- "Sportmonks model-performance information" (spec: "Also store ... where
  available") — no live token was available to confirm Sportmonks
  exposes this as a distinct endpoint/field. Rather than guess at a
  schema for something unverified, it's covered by what Phase 3 already
  does: `sportmonks_predictions.raw_payload` preserves the full raw
  response, so nothing is lost; there's simply nothing further to
  normalize into its own column without a real payload to check against.

**Tests** (`backend/tests/`, 238 total — 7 new, all passing)

`test_sportmonks_service.py` (real PostgreSQL): copies the probability
correctly; returns `None` with no ingested prediction, or when the
probability field itself is null (BTTS-only rows, say); preserves an
existing row's `predicted_at`; the batch driver merges without
clobbering `poisson_probability`, records a clear failure for a fixture
with nothing ingested, and is idempotent on re-run.

**Remaining risks** — same as Phase 3: payload shape and the "model
performance" question above are unverified against a live Sportmonks
account.

## Phase 10 — Odds and market edge

Like Phase 9, most of the hard work (leakage-guarded ingestion, and the
math itself) already happened: Phase 3's `ingest_odds_for_fixture` stores
bookmaker snapshots with `retrieved_at < kickoff` enforced, and Phase 2's
schema computes `odds.market_probability` (de-vigged) and
`model_predictions.edge` (`final_probability - market_probability`) as
PostgreSQL generated columns. Phase 10 is the integration step: pick a
market snapshot and sync it in — at which point `edge` computes itself.

**What was built**

- `backend/app/models/odds_service.py` — `build_market_snapshot` takes
  the *latest* odds row per bookmaker for a fixture (not every historical
  snapshot), keeps only ones with a *plausible* overround (`1.0 <
  overround < 1.30` — a data-quality guard against stale/malformed odds
  feeding a misleading edge), and averages `market_probability`/
  `market_odds_over`/`market_odds_under` across whichever bookmakers
  qualify. `odds_id` is only set when exactly one bookmaker informed the
  snapshot (traceable to a specific row); with multiple bookmakers
  averaged together, it's left `NULL` rather than pointing at an
  arbitrarily-chosen one. **The module never reads
  `over_implied_probability`/`under_implied_probability`** (the raw,
  vig-inflated figures) — only the de-vigged `market_probability` — which
  is the concrete enforcement of the spec's "do not call a selection a
  value bet solely because the model probability is higher than the raw
  bookmaker implied probability."
  `sync_and_store_market_data` is the usual per-item-isolated batch
  driver, carrying forward `predicted_at` as Phase 8/9 established.
- `backend/app/models/odds_cli.py` — `python -m app.models.odds_cli sync
  --start ... --end ...`.

**Tests** (`backend/tests/`, 248 total — 10 new, all passing)

`test_odds_service.py` (real PostgreSQL) — a source-level guard proving
the module never *accesses* the raw implied-probability fields (only
mentions them in its docstring, to explain why not); the snapshot's
`market_probability` matches the DB-computed de-vigged figure and is
verified numerically different from the raw implied probability;
averaging across multiple bookmakers; using each bookmaker's *latest*
snapshot rather than a stale earlier one; an implausible overround
rejected; **`edge` verified to fall out of Phase 2's generated column
automatically** once `market_probability` and `final_probability` are
both present — no Python computes it; failure/idempotency handling.

**Remaining risks** — same as Phase 3/9: no real odds have been ingested
in this session (no live Sportmonks token, and `ODDS_MARKET_ID_OVER_UNDER`
in `sportmonks_reference.py` is still a placeholder). The overround
plausibility bounds (1.0–1.30) are a reasonable default, not tuned
against real market data.

## Phase 11 — Ranking engine

Ties everything together: league filtering, `confidence_score`,
`ranking_score`, and the daily Top N.

**What was built**

- `backend/app/ranking/league_reliability.py` — `league_reliability_score`
  is a **multiplicative** combination of sample-size adequacy × Brier
  quality × calibration quality (all in `[0,1]`), sample-size-weighted
  across whichever `backtest_run_ids` are supplied (typically every fold
  of one walk-forward execution, so the score reflects the whole tested
  history). Multiplicative, not averaged, on purpose — a league with
  plenty of samples but badly miscalibrated predictions must not average
  out to a middling score; any one weak dimension pulls the whole score
  down, which `test_multiplicative_combination_is_stricter_than_averaging`
  proves directly. A league is `is_eligible` only above both a score
  threshold and a minimum sample size.
- `backend/app/ranking/confidence.py` — `confidence_score` (the
  platform's explicitly required third quantity, distinct from
  probability and edge) = `data_completeness × league_reliability ×
  model_agreement`. Model agreement drops as the available probability
  sources (poisson/ml/sportmonks) disagree more; with only one source to
  begin with, agreement is a fixed, documented default rather than either
  extreme.
- `backend/app/ranking/scoring.py` — `ranking_score` is confidence-weighted
  probability, plus a **confidence-gated** boost for positive edge only.
  Negative or absent edge never penalizes a fixture, and a large edge
  from a low-confidence prediction contributes little — the concrete
  enforcement of "do not call a selection a value bet solely because the
  model disagrees with the market."
- `backend/app/ranking/daily_ranking_service.py` — `build_daily_ranking`
  fetches a date's not-started fixtures, excludes any with no stored
  prediction, no features, an ineligible league, or confidence below a
  floor, ranks what's left by `ranking_score`, and stores the top N.
  Written delete-then-insert per `ranking_date` (documented in the module
  docstring) rather than upserted, since which fixtures qualify — and
  their ranks — can change run to run; there's no stable per-row key to
  upsert against.
- `backend/app/ranking/cli.py` — `python -m app.ranking.cli
  league-reliability` and `... daily --date ...`.

**Tests** (`backend/tests/`, 280 total — 32 new, all passing)

- `test_league_reliability.py` / `test_confidence_and_scoring.py` (pure):
  every scoring formula against hand-reasoned cases — zero sample size,
  perfect metrics at full sample, proportional sample-size scaling, a
  poor Brier or calibration score tanking an otherwise-good score, the
  multiplicative-vs-averaging regression guard, confidence provably
  distinct from probability with identical inputs otherwise, positive
  edge boosting `ranking_score` while negative edge never penalizes it,
  and the edge boost being smaller at lower confidence.
- `test_league_reliability_service.py` / `test_daily_ranking_service.py`
  (real PostgreSQL): aggregation across multiple backtest runs;
  low-sample leagues correctly ineligible; re-running updates in place;
  **the full exclusion pipeline** — an ineligible league, a fixture
  missing a prediction, and a fixture with data too thin to be confident
  are each excluded with a clear, distinct reason string; qualifying
  fixtures rank highest-`ranking_score`-first; `top_n` is respected;
  re-running the same date clears the prior ranking rather than
  duplicating; only not-started fixtures on the target date are
  considered.

**Remaining risks**

- Phase 7's walk-forward loop only backtests `poisson`/`ml` by default —
  extending it to backtest the fully-calibrated `'final'` model per fold
  (each needing its own ensemble-fitting validation carve-out) is a
  larger, separate piece of work, flagged rather than built here.
  `league-reliability`'s `--model-type` is deliberately caller-specified
  so operators can point it at whichever model_type they've actually
  backtested in the meantime.
- Every threshold here (`MIN_RELIABLE_SAMPLE_SIZE`, `MAX_ACCEPTABLE_BRIER`,
  `ELIGIBILITY_SCORE_THRESHOLD`, `DEFAULT_MIN_CONFIDENCE`,
  `EDGE_BOOST_WEIGHT`, …) is a reasonable, documented default — none has
  been tuned against real outcomes, since no real historical data has
  been backtested in this session.

## Phase 12 — Dashboard (Next.js)

Before this phase, the backend had no way to expose data — only the
Phase 1 health checks existed. Phase 12 is therefore two pieces: a
read-only FastAPI API layer (`backend/app/api/`), then the six-page
Next.js dashboard consuming it.

**Backend: the read API**

- `backend/app/api/schemas.py` — hand-picked Pydantic response models,
  never the ORM objects themselves, so the frontend contract stays
  stable independent of internal column changes and nothing internal
  leaks by accident.
- `backend/app/api/routes/` — `GET /api/rankings/daily`,
  `GET /api/fixtures/{id}`, `GET /api/leagues/performance`,
  `GET /api/models/performance`, `GET /api/backtest/runs`,
  `GET /api/system/health`. Full reference: `docs/API.md`. All read-only;
  the API never accepts writes, by design — every CLI pipeline built in
  Phases 3–11 remains the only way data changes.
- CORS is explicit-allowlist (`CORS_ALLOWED_ORIGINS`, default
  `http://localhost:3000`), never a wildcard.

**Frontend: the dashboard**

- `frontend/` — Next.js 16 (App Router) + React 19 + TypeScript +
  Tailwind CSS 4, scaffolded fresh via `create-next-app`. The scaffold's
  own `AGENTS.md` (regenerated by `next dev`, meant to be committed) flags
  that this Next.js version may differ from older training data — its
  bundled docs (`node_modules/next/dist/docs/`) were read before writing
  any page, in particular confirming `cache: "no-store"` still works as
  the explicit no-cache escape hatch under the version's default
  (non-Cache-Components) rendering model, which every page here uses.
- All six required pages, each a Server Component fetching directly from
  the backend with `export const dynamic = "force-dynamic"` — this
  dashboard's data changes as often as the CLI pipelines run, so nothing
  here should ever serve a stale build-time snapshot.
- `probability`, `confidence`, and `market edge` are visually distinct
  everywhere they appear (`ProbabilityPill`/`ConfidencePill`/`EdgePill` in
  `src/components/ui.tsx` — blue / violet / green-or-red), and every page
  carries the same footer disclaimer ("Predictions are probability
  estimates, not guarantees...") — the platform's core rule made visible,
  not just enforced in the data model.

**Verification** — this was checked as a real, running app, not just
compiled: `npx tsc --noEmit`, `npm run lint`, and `npm run build` are all
clean, and beyond that, the backend and frontend dev servers were both
run locally against a PostgreSQL database seeded with a realistic
fixture end-to-end (league, teams, features, a full model_predictions
row, league reliability, a backtest run, and a daily ranking). Every one
of the six pages' rendered HTML was confirmed (via curl against the
running dev server, not a mock) to contain the actual seeded values —
not placeholder markup — including the empty state (a ranking date with
no data) and the 404 state (an unknown fixture id). See
`frontend/README.md` for the full verification note.

**Remaining risks**

- No real historical data exists in this session, so the dashboard has
  only ever displayed synthetic/seeded data, never a real prediction run.
- No authentication on the API — appropriate for a read-only surface
  serving already-derived, non-sensitive data, but worth revisiting
  before any write endpoint is added.
- Visual polish is functional-clean, not extensively designed — no
  charts (e.g. a calibration plot) beyond the probability-band table;
  reasonable for a first pass, a candidate for follow-up.

## Phase 13 — Automation (n8n)

Ties every previous phase's CLI into one daily run: the spec's twelve
AUTOMATION steps, executed in order, with per-step failure isolation.

**What was built**

- `backend/app/automation/daily_pipeline.py` — `run_daily_pipeline`
  fetches the target date's upcoming (`NS`) fixtures and then runs, in
  order: fixture retrieval, Sportmonks prediction retrieval, feature
  computation, Poisson/ML/Sportmonks-sync/ensemble-and-calibration
  prediction generation, odds retrieval, market probability sync, ranking
  (which computes confidence and stores the Top N in one call), and the
  daily report. Each step is wrapped individually — one step's exception
  (most commonly: no trained ML artifact yet) is caught, logged, and
  recorded in the returned `DailyPipelineReport` as a failed `StepResult`
  without stopping the rest of the run, the same failure-isolation
  philosophy every batch operation in this codebase already follows.
  Steps that don't correspond to a separate action in this codebase's data
  model — "calculate edge" (a Phase 2 generated column) and "calculate
  confidence"/"store the Top 10" (both internal to Phase 11's
  `build_daily_ranking`) — are still recorded in the report, with a detail
  string pointing at where the real work actually happens, rather than
  fabricating a no-op action for them.
- Model training (Phase 6), backtesting (Phase 7), and league-reliability
  scoring (Phase 11) are **deliberately not** part of this daily pipeline
  — they're periodic/on-demand jobs (see `docs/DEPLOYMENT.md`), not
  something that needs to re-run every day. The pipeline assumes a
  trained ML artifact, a fitted ensemble/calibration config, and at least
  one `league_model_performance` computation already exist; if any are
  missing, the corresponding step fails cleanly with a clear reason
  rather than crashing the run.
- `backend/app/automation/report.py` — `generate_daily_report` builds a
  human-readable summary of the day's ranked selections (each with
  probability, confidence, and edge shown as the separate figures they
  are, plus the platform's standing "not guarantees" disclaimer) or a
  clear "no qualifying selections today" message. `send_report` delivers
  it via a generic webhook POST (`DAILY_REPORT_WEBHOOK_URL`) rather than a
  specific vendor integration — no credentials for any one provider
  (email, Slack, ...) were available to build and test against, and a
  JSON webhook is what every mainstream chat/email-relay tool already
  knows how to receive (Slack incoming webhooks, Discord, n8n's own
  Webhook node, Zapier, ...). If no URL is configured, the report is
  logged instead — a safe, functional default that never silently drops
  it, and delivery failure falls back to logging rather than raising.
- `backend/app/automation/cli.py` — `python -m app.automation.cli run
  [--date YYYY-MM-DD]`, the single command a scheduler needs to invoke.
  Exits `0` if every step succeeded, `1` otherwise, logging each step's
  status and detail.
- `platform/automation/n8n-daily-pipeline.json` — an importable n8n
  workflow: a daily Schedule Trigger, an Execute Command node running the
  CLI above, and a failure branch that posts an alert to a separate
  ops-facing webhook. `docs/DEPLOYMENT.md` covers importing and adapting
  it, plus the plain-cron alternative.
- `docs/DEPLOYMENT.md` — the platform's deployment guide: database
  (Supabase/any PostgreSQL), backend API hosting, the Vercel frontend
  deploy, and scheduling the daily pipeline (n8n or cron), plus which
  jobs stay manual/periodic by design.

**A real, important bug this phase's tests caught:** every sub-service
this pipeline calls (`ingest_fixtures_between`,
`compute_and_store_features_for_fixtures`,
`compute_and_store_poisson_predictions`, etc.) commits its own work by
default (`commit=True`) — correct for a real scheduled run, where partial
progress should persist even if a later step fails. But it silently broke
the test suite's `db_session` fixture, which relies on an outer
connection-level transaction rolled back at teardown for isolation:
calling `session.commit()` on that fixture's session commits the
underlying transaction for real, and the rollback at teardown becomes a
no-op. Running the pipeline's integration test once permanently wrote a
mocked test league into the shared `football_platform_test` database,
which then collided with a later test's own seed data
(`UniqueViolation` on `leagues.id`). Fixed by threading a `commit: bool =
True` parameter through `run_daily_pipeline` into every sub-service call
(all of which already supported it individually) and into the pipeline's
own two manual `session.commit()` calls, so tests can pass `commit=False`
and preserve the fixture's rollback-based isolation while production
usage keeps the desirable default. The polluted rows were cleaned up
directly in the test database, and the tests were also fixed to `flush()`
their own seed data rather than `commit()` it, for the same reason.

**Tests** (`backend/tests/`, 297 total — 17 new, all passing)

- `test_automation_report.py` — report text includes the right teams,
  league, probability/confidence/edge figures, and the "not a guarantee"
  disclaimer; a date with no ranking produces a clear empty-state message
  instead of an empty report; `send_report` logs (and returns `False`)
  with no webhook configured, posts to a configured webhook and returns
  `True`, and falls back to logging (returning `False`, not raising) when
  delivery fails.
- `test_daily_pipeline.py` (real PostgreSQL, mocked Sportmonks HTTP) —
  every one of the fifteen recorded steps runs in the documented order;
  missing prerequisites (no trained ML artifact / ensemble config) are
  isolated failures that don't stop the rest of the run, and the fixture
  itself is still ingested despite them; given seeded history and
  pre-trained artifacts, a full run produces an actual stored
  `DailyRanking` and a `ModelPrediction` row with every probability source
  populated and a positive Poisson ensemble weight — proving the
  orchestration and data flow work end to end, not just that each step
  runs in isolation.

Run them yourself (requires a local PostgreSQL instance):

```bash
cd platform/backend
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test
python3 -m pytest -v
```

**Remaining risks**

- No real scheduler (n8n or cron) has actually executed this pipeline
  against a live deployment in this session — the workflow template and
  `docs/DEPLOYMENT.md` follow n8n's and cron's documented conventions but
  are unverified against a running instance.
- No `DAILY_REPORT_WEBHOOK_URL` provider has been exercised against a
  real endpoint (Slack/Discord/...) — `send_report`'s POST is a generic
  `{"text": ...}` JSON body, which Slack/n8n-style incoming webhooks
  accept directly, but a provider requiring a different payload shape
  would need a small adapter.
- Same as every phase relying on live ingestion (3/9/10): no real
  Sportmonks token has been used in this session, so the pipeline's
  Sportmonks-prediction and odds-retrieval steps are verified only
  against mocked HTTP responses.
- This is the last of the thirteen planned phases. The platform as built
  is functionally complete end to end (ingestion → features → three
  prediction sources → ensemble/calibration → backtesting →
  league-reliability-filtered ranking → dashboard → daily automation) but
  has only ever run against synthetic/seeded data and mocked Sportmonks
  responses — see "Remaining risks" in Phases 1, 3, 6, 9, 10, and 12 for
  what a real deployment still needs to verify against a live Sportmonks
  token and real historical data before going live.

## Phase 14 — 15-point checklist

A second, independent scoring system alongside the probability/confidence/
edge pipeline above — requested as a rule-based checklist covering BTTS
rate, clean sheet rate, combined goals, league position gap, shots on
target, xG, head-to-head, recent form, league averages, goal timing, and
missing players/context, deliberately never combined into the main model's
output (the two are shown on separate dashboard pages, on purpose — a
checklist score and a calibrated probability answer different questions and
conflating them would misrepresent both).

**What was built**

- `backend/app/checklist/checks.py` — the 13 scored items as pure functions,
  each returning `True`/`False`/`None` ("N/A" — never a guessed value when a
  check can't be evaluated). Two items needed a documented interpretation
  call where the original wording was ambiguous against what data actually
  exists: item 8 (xG) sums both teams' xG-for and xG-against, and item 11
  (vs league average) compares each team against that league's
  venue-specific average (home vs league home-goals average, away vs
  league away-goals average) rather than one blended figure, since
  `match_features` already stores those separately.
- `backend/app/checklist/standings.py` — computes a league table purely
  from stored fixture results (points, goal difference, position) — no new
  ingestion needed, and leakage-safe by the same `kickoff < before`
  discipline as every other feature in this codebase.
- `backend/app/checklist/service.py` — gathers each team's current-season
  history (reusing Phase 4's `fetch_team_appearances`) and this matchup's
  standings/head-to-head context, calls the check functions, and stores one
  row per fixture in the new `checklist_scores` table. Item 1 (sample size)
  is the one item that excludes a fixture entirely rather than scoring it
  N/A, per the spec: a fixture where either team has fewer than 5 games
  played this season never gets a row, and the batch driver records that
  as an isolated failure, same pattern as every "insufficient data" case
  elsewhere in this codebase.
- `backend/app/checklist/cli.py` — `python -m app.checklist.cli build
  --start ... --end ...`.
- `backend/app/api/routes/checklist.py` — `GET
  /api/checklist/daily?checklist_date=...`, read-only like every other
  endpoint.
- `frontend/src/app/checklist/page.tsx` — the **15-Point Checklist**
  dashboard page: a date picker, sorted by score, every check shown as a
  ✓/✗/— column (hover a header for the full description), plus context
  notes and an honest data-gaps disclosure per fixture.

**Honest data-gap accounting** (the spec's own explicit requirement: never
fake a stat, always disclose what's missing) — items 6 (shots on target)
and 8 (xG) are computable in principle now that Phase 9's real Sportmonks
type IDs are configured, but only once match_statistics/match_xg are
actually backfilled (`--with-statistics` on historical ingestion, not run
by default); items 12-13 (goal timing) are always N/A — no events/
goal-timeline table exists anywhere in this schema yet, a genuine gap for
a future phase, not a bug; item 14 (missing players) always reports
`"Unknown"` — no injuries data source is hooked up. Every one of these
shows up in the stored `data_gaps` text rather than silently vanishing.

**Tests** (`backend/tests/`, 319 total — 21 new, all passing)

- `test_checklist_checks.py` (pure): every one of the 13 check functions
  against a clear pass, a clear fail, and the missing-data N/A case.
- `test_checklist_standings.py` (real PostgreSQL): correct points/goal-
  difference ordering; a match at or after the cutoff never affects the
  table (leakage boundary); a team with no qualifying matches is omitted,
  not given a false position.
- `test_checklist_service.py` (real PostgreSQL): a fully-populated fixture
  produces the exact hand-computed result across all 13 items; the target
  fixture's own result is proven never to leak into its own checklist; a
  fixture below the 5-games threshold is excluded, not scored; the batch
  driver stores qualifying fixtures, records excluded ones as failures,
  and is idempotent on re-run.
- Two new cases in `test_api.py` for the `/api/checklist/daily` route.
- Verified as a real, running page — not just compiled: `npx tsc --noEmit`,
  `npm run lint`, and `npm run build` all clean, and the backend/frontend
  dev servers were run together against a seeded database, with the
  rendered HTML confirmed (via curl against the running server) to contain
  real seeded team names, score, relegation-zone context note, and
  data-gaps text — not placeholder markup.

**Remaining risks**

- Goal-timing (items 12-13) and missing-players (item 14) data sources
  don't exist in this platform yet — real, flagged gaps, not silently
  faked. Building them would mean a new fixture-events ingestion path (and
  table) and an injuries/sidelined integration respectively — both
  reasonable future phases, deliberately not built here to avoid scope
  creep into this phase.
- The two documented interpretation calls (items 8 and 11, above) reflect
  a reasonable, data-grounded reading of ambiguous spec wording, not the
  only possible one — worth revisiting if the intended meaning was
  different.
- No real deployment has exercised `--with-statistics` backfill in this
  session, so items 6/8 have only ever been verified as correctly N/A
  (the honest state), never as a genuinely populated TRUE/FALSE against
  real shots-on-target/xG data.

See `docs/SETUP.md` for environment setup instructions, `docs/DATABASE.md`
for the full schema reference, `docs/BACKTEST.md` for backtesting
methodology, `docs/MODEL.md` for the full modeling writeup, `docs/API.md`
for the read API the dashboard consumes, and `docs/DEPLOYMENT.md` for
running the platform in production.
