# Model

How this platform turns pre-match features into a single calibrated
Over 2.5 probability, and why each layer exists. Implementation:
`backend/app/models/`.

## Pipeline overview

```
team_features / match_features (Phase 4)
        |
        +--> Poisson model (app/models/poisson.py)        -> poisson_probability
        +--> XGBoost model (app/models/xgboost_model.py)   -> ml_probability
        +--> Sportmonks' own prediction (Phase 9)           -> sportmonks_probability
                        |
                        v
         ensemble weighting (app/models/ensemble.py)
                        |
                        v
              raw_ensemble_probability
                        |
                        v
        calibration (app/models/calibration.py)
                        |
                        v
               final_probability
```

Every stage writes to the same `model_predictions` row per
`(fixture_id, model_version)` — see "Shared model_version" below.

## Poisson baseline (`app/models/poisson.py`)

Independent-Poisson attack/defense-strength model. For a fixture with
home team *i*, away team *j*:

```
mu_home = league-wide avg goals scored BY HOME teams   (= match_features.league_home_goals_avg)
mu_away = league-wide avg goals scored BY AWAY teams   (= match_features.league_away_goals_avg)

home_attack   = i's avg goals scored at home / mu_home
away_defense  = j's avg goals conceded away  / mu_home   <- normalized against mu_home, not mu_away
expected_home_goals = mu_home * home_attack * away_defense

away_attack   = j's avg goals scored away  / mu_away
home_defense  = i's avg goals conceded at home / mu_away  <- normalized against mu_away, not mu_home
expected_away_goals = mu_away * away_attack * home_defense

lambda_total = expected_home_goals + expected_away_goals
P(Over 2.5)  = 1 - exp(-lambda_total) * (1 + lambda_total + lambda_total^2/2)
             = P(X >= 3) for X ~ Poisson(lambda_total)
```

**Why the defense ratios cross-normalize** (a classic mix-up in these
models): a team's away-conceded total is, league-wide, drawn from the
*same* distribution as home teams' scoring — it's the same goals, counted
from the other side. So `away_defense` normalizes against `mu_home`, and
`home_defense` against `mu_away`. Getting this backwards silently produces
a plausible-looking but wrong number;
`test_estimate_poisson_defense_normalized_against_opposite_league_average`
exists specifically to catch a regression here with deliberately
asymmetric inputs.

Team goal rates come from Phase 4's `venue_last{W}_*` features (the home
team's home record, the away team's away record — exactly what the
formula needs), falling back to `overall_last{W}_*` if a team has no
venue-specific history yet. `window` defaults to 10 matches. Returns
`None` — never a fabricated number — when the league baseline or a team's
rate isn't available.

No training step: nothing here is fit to data beyond what Phase 4's
rolling features already encode, so it's evaluated identically whether
the fixture is historical or upcoming.

## XGBoost (`app/models/xgboost_model.py`, `dataset.py`,
`chronological_split.py`)

A `binary:logistic` classifier trained on one row per finished fixture:
Phase 4's `team_features` (home/away-prefixed) + `match_features`, target
`over_2_5`. Missing values (expected — box-score stats/xG are `None`
until Phase 3's placeholder type IDs are configured; early-season rolling
windows are naturally incomplete) go straight to XGBoost's native
missing-value handling rather than being imputed.

**Splitting is always chronological, never random** — filtering by
kickoff date rather than sampling, so there is no shuffling step that
could leak a later match into an earlier partition. Training uses only
the train partition; the validation partition is used solely for early
stopping and reporting metrics, never gradient updates.

Trained models are self-describing filesystem artifacts
(`backend/artifacts/xgboost/{model_version}.json` + a `.meta.json`
sidecar recording the exact feature-column order, training window, and
validation metrics) rather than a database row — there is no "trained
model" table in the schema, and this is the standard alternative.
Prediction loads the artifact once per batch and reuses it.

## Ensemble (`app/models/ensemble.py`)

`raw_ensemble_probability` is a weighted combination of
`poisson_probability` / `ml_probability` / `sportmonks_probability`.
Weights are **fit on validation data** by minimizing validation log loss
(a constrained convex-combination optimization, via `scipy.optimize`) —
never fixed or assumed permanently, per spec. A source only gets a
non-zero weight if it has ≥80% coverage (non-null rate) in the validation
set; below that, its weight is `0.0`, not a guess. This is why
`sportmonks_probability` — entirely absent until Phase 9 — currently
contributes nothing: the mechanism is ready, and re-fitting once real
Sportmonks data exists is how it earns a weight.

At prediction time, a specific fixture's ensemble combination renormalizes
over whichever weighted sources are actually present on that row, so one
missing source falls back to the others rather than silently shrinking
the result.

## Calibration (`app/models/calibration.py`)

Raw ensemble probabilities aren't necessarily well-calibrated (a model
can be discriminative — good at ranking — while still being systematically
over- or under-confident). Two calibration methods are fit on validation
data:

- **Platt scaling**: a 1-D logistic regression of the true outcome on the
  raw probability — a smooth sigmoid correction.
- **Isotonic regression**: a non-parametric, monotonic step function —
  more flexible, but needs more validation data to fit reliably.

**The method itself is selected on validation data** (whichever achieves
lower validation log loss), per spec — never a fixed choice. With fewer
than 10 validation rows, or only one class present, calibration falls
back to `"none"` (identity) rather than fitting something unreliable.

Both calibrators serialize to small, self-contained parameter sets (not
pickled sklearn objects), so applying a saved calibrator later depends
only on plain arithmetic (`numpy`), never on sklearn or matching library
versions.

## Shared `model_version`

Every phase that contributes to `model_predictions` — Poisson (5), ML
(6), ensemble/calibration (8), Sportmonks (9) — writes to the same
`(fixture_id, model_version)` row (`app/models/constants.py:DEFAULT_MODEL_VERSION`,
currently `"v1"`). The generic upsert (`app/common/upsert.py`) only sets
the columns present in each call's `values` dict, so later phases fill in
more columns on the same row without clobbering what an earlier phase
already wrote — proven by tests in each phase that seed one column and
verify a later upsert leaves it untouched.

Backtesting (Phase 7) is the one exception: each walk-forward fold trains
its own ML artifact under a **different** `model_version`
(`backtest-{fold_label}`), so backtest evaluation is never confused with,
or able to overwrite, the "production" `v1` row.

## What's still open

- No real historical data has been ingested in this session (no live
  Sportmonks token). Every model/ensemble/calibration behavior described
  here is verified against synthetic data with a known, controlled
  relationship to the label — not a real trained model.
- Hyperparameters (XGBoost's `DEFAULT_PARAMS`, the ensemble's coverage
  threshold, calibration's minimum-validation-rows cutoff) are reasonable
  defaults, not the product of tuning against real outcomes.
- `confidence_score` (distinct from probability, per the platform's core
  rule) is not computed by this phase — that's Phase 11 (ranking engine).
