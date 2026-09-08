# Database

PostgreSQL, managed with SQLAlchemy 2.0 models and Alembic migrations.
Schema source of truth: `backend/app/db/models/`. Migrations:
`backend/alembic/versions/`.

## Design principles

- **Sportmonks IDs are primary keys.** `leagues`, `teams`, `seasons`, and
  `fixtures` use the Sportmonks entity ID directly as their primary key
  (no surrogate ID / mapping table). This makes ingestion idempotent:
  upserts key on the ID Sportmonks returns.
- **Generated columns for anything that must never drift.** `fixtures`
  computes `total_goals` and `over_2_5` as PostgreSQL `GENERATED ALWAYS AS
  ... STORED` columns, derived only from `home_goals`/`away_goals`. No
  application code path can set the Over 2.5 label independently or
  inconsistently with the final score — the rule
  `over_2_5 = 1 if home_goals + away_goals >= 3 else 0` is enforced by the
  database itself, and is `NULL` until both goal counts are known.
  `odds` (implied probabilities, overround, de-vigged `market_probability`)
  and `model_predictions.edge` (`final_probability - market_probability`)
  are generated the same way, so a derived value can never disagree with
  the inputs it was computed from.
- **Every table has `created_at`/`updated_at`.** Server-side defaults
  (`now()` / `now()` on update), via a shared `TimestampMixin`.
- **Delete semantics are deliberate, not default.** Reference data
  (`leagues`, `teams`, `seasons`) is `ON DELETE RESTRICT` from `fixtures` —
  you cannot silently orphan a fixture by deleting a team. Everything that
  is *derived from* a fixture (`match_statistics`, `match_xg`,
  `sportmonks_predictions`, `odds`, `team_features`, `match_features`,
  `model_predictions`, `daily_rankings`) is `ON DELETE CASCADE` on
  `fixture_id` — meaningless without the fixture it describes.
- **Leakage guards that the schema can't fully enforce are documented,
  not silently assumed.** `sportmonks_predictions.retrieved_at`,
  `odds.retrieved_at`, and `model_predictions.predicted_at` must all be
  `<= fixtures.kickoff` for that row to be valid to use in
  historical feature/label generation. PostgreSQL CHECK constraints
  cannot reference another table's column, so this is enforced in the
  ingestion/feature-engineering application code (Phase 3+) and covered
  by dedicated leakage-protection tests — it is *not* currently enforced
  by a database constraint. Treat any row that violates it as a bug.

## Tables

| Table | Purpose | Key relationships |
|---|---|---|
| `leagues` | Reference: competitions | — |
| `teams` | Reference: clubs | — |
| `seasons` | Reference: one season of one league | `league_id -> leagues` (RESTRICT) |
| `fixtures` | One match. `total_goals`/`over_2_5` are generated columns. | `league_id -> leagues`, `season_id -> seasons`, `home_team_id`/`away_team_id -> teams` (all RESTRICT) |
| `match_statistics` | Per-team box-score stats for one fixture | `fixture_id -> fixtures` (CASCADE), `team_id -> teams` (RESTRICT); unique per (fixture, team) |
| `match_xg` | Per-team xG for one fixture (xGA = opponent's row) | same as above |
| `sportmonks_predictions` | Sportmonks' own pre-match model output, as pulled at `retrieved_at` | `fixture_id -> fixtures` (CASCADE), unique per fixture |
| `odds` | Bookmaker Over/Under 2.5 snapshot; implied probabilities, overround and de-vigged `market_probability` are generated columns | `fixture_id -> fixtures` (CASCADE); unique per (fixture, bookmaker, market, retrieved_at) |
| `team_features` | One row per (team, fixture): that team's rolling pre-match form, in `overall_lastN_*` and venue-specific `venue_lastN_*` variants, each with a `*_matches_played` sample-size column | `team_id -> teams` (RESTRICT), `fixture_id -> fixtures` (CASCADE); unique per (team, fixture) |
| `match_features` | Fixture-level features not specific to one team: league context + head-to-head history. Per-team rolling form is obtained by joining `team_features` on `fixtures.home_team_id`/`away_team_id`, not duplicated here. | `fixture_id -> fixtures` (CASCADE), PK |
| `model_predictions` | Every probability this system produces for a fixture: `poisson_probability`, `ml_probability`, `sportmonks_probability`, `raw_ensemble_probability`, `final_probability` (post-calibration), plus `confidence_score` (never conflated with probability) and `edge` (generated, `final_probability - market_probability`) | `fixture_id -> fixtures` (CASCADE), `odds_id -> odds` (SET NULL); unique per (fixture, model_version) |
| `backtest_results` | Walk-forward evaluation metrics, sliced by `model_type` and by `segment_type`/`segment_value` (league / season / probability band / home-away / overall) | unique per (run, model_type, segment_type, segment_value) |
| `league_model_performance` | Per-league reliability scoring (`league_reliability_score`, `is_eligible`) used to filter leagues out of the daily ranking | `league_id -> leagues` (CASCADE); unique per (league, model_type, evaluation_window_end) |
| `daily_rankings` | The generated Top N for a given day, with rank enforced unique per day | `fixture_id -> fixtures` (CASCADE), `model_prediction_id -> model_predictions` (RESTRICT); unique per (date, fixture) and per (date, rank) |

### `team_features` column naming

Generated programmatically (not hand-typed) as
`{context}_last{window}_{stat}` plus `{context}_last{window}_matches_played`,
for:

- `context` in `overall`, `venue` (venue = home-only rolling form if this
  team is the home team in the target fixture, away-only if away)
- `window` in `3`, `5`, `10`
- `stat` in `goals_scored`, `goals_conceded`, `xg`, `xga`, `shots`,
  `shots_on_target`, `big_chances`, `corners`, `btts_pct`, `over_2_5_pct`

66 columns total (10 stats x 3 windows x 2 contexts, plus 6 sample-size
columns). See `app/db/models/features.py:_team_feature_column_names()`.

## Migrations

```bash
cd platform/backend
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/football_platform
alembic upgrade head          # apply
alembic revision --autogenerate -m "..."   # after changing models
alembic downgrade base        # tested reversible: drops everything cleanly
```

`alembic/env.py` reads the connection string from `DATABASE_URL` (env var
directly, or via `Settings`) — never hard-coded in `alembic.ini`.

## Testing

- `tests/test_db_schema.py` — structural checks on the SQLAlchemy metadata
  (required tables present, every table has a PK and timestamps, cascade
  rules correct, target-label columns exist). No database needed.
- `tests/test_db_integration.py` — runs against a real PostgreSQL database
  (`TEST_DATABASE_URL`, defaults to
  `postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test`;
  tests skip cleanly if it isn't reachable). Proves: the Over 2.5 label is
  computed correctly for every goal combination (including the "one goal
  still missing" case, which must stay `NULL`, not a false 0/1); status
  and goals CHECK constraints reject bad data; FK constraints reject
  orphaned rows; unique constraints reject duplicate
  `(team, fixture)` / `(date, rank)` rows; `odds` de-vig and
  `model_predictions.edge` generated columns compute the correct value;
  deleting a fixture cascades to its dependent rows; deleting a team that
  a fixture references is blocked.

Each integration test runs inside a database transaction that is rolled
back at teardown, so the suite is self-cleaning and safe to run repeatedly
against the same database.
