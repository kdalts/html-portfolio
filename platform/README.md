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
| 2 | Database schema | **Done** |
| 3 | Historical data ingestion | **Done** |
| 4 | Feature engineering | **Done** |
| 5 | Poisson baseline model | **Done** |
| 6 | XGBoost model | **Done** |
| 7 | Backtesting (walk-forward) | **Done** |
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

See `docs/SETUP.md` for environment setup instructions, `docs/DATABASE.md`
for the full schema reference, and `docs/BACKTEST.md` for backtesting
methodology.
