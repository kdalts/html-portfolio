# Backtesting

Walk-forward validation for every prediction model in this platform.
Implementation: `backend/app/backtest/`.

## Methodology: expanding-window walk-forward

Per spec, an expanding training window with a fixed start date:

| Fold | Train | Test |
|---|---|---|
| 1 | 2019–2022 | 2023 |
| 2 | 2019–2023 | 2024 |
| 3 | 2019–2024 | 2025 |

`app/backtest/walkforward.py:default_folds()` encodes exactly this.
Custom fold sets can be passed to `run_walkforward_backtest(folds=...)`.

**No shuffling, anywhere.** Every split in this codebase — the
train/val/test split inside a single fold (`chronological_split`,
Phase 6) and the walk-forward folds themselves — is a filter on kickoff
date, never a random sample. There is no code path that could shuffle a
later match into an earlier partition.

**Per-model retraining policy:**

- **Poisson** has no learned parameters beyond what's already baked into
  Phase 4's rolling features (which are themselves leakage-safe by
  construction — see `docs/DATABASE.md` / the Phase 4 README section).
  So each fold's Poisson predictions are computed directly from that
  fold's test fixtures' already-stored features; no retraining needed.
- **XGBoost** genuinely learns parameters from training data, so each
  fold trains its **own** model using only `[train_start, train_end)` —
  reusing a single "production" model (like the one Phase 6's CLI trains)
  across folds would let a fold's test evaluation be produced by a model
  that had already seen future data relative to that fold, silently
  invalidating the whole exercise. Within a fold's training window, the
  last `validation_fraction` (default 15%) by time is carved out as the
  early-stopping validation set — that boundary is still inside
  `[train_start, train_end)`, never touching the fold's test period.
  `test_walkforward_ml_model_never_trains_on_data_at_or_after_train_end`
  proves this directly from the saved artifact's own metadata file rather
  than trusting the code's intent.

Fold-specific ML artifacts are saved under `model_version =
f"backtest-{fold.label}"` (e.g. `backtest-2023`), separate from the
"production" `v1` model_predictions row Phase 5/6 write to — a backtest
run must never be confused with, or overwrite, a live prediction.

## Metrics (`app/backtest/metrics.py`)

All standard, computed with scikit-learn, every one returning `None`
(never a fabricated number) when undefined:

| Metric | Definition | None when |
|---|---|---|
| Log Loss | binary cross-entropy | < 2 classes present, or empty |
| Brier Score | mean squared error of the probability | empty |
| ROC-AUC | area under the ROC curve | < 2 classes present, or empty |
| Accuracy | fraction correct at a 0.5 decision threshold | empty |
| Precision | of predicted-Over calls (`p >= 0.5`), fraction correct | empty (0.0 if no positive calls, not NaN) |
| Recall | of actual Overs, fraction the model called | empty (0.0 if no positive calls) |
| Calibration Error | see below | nothing bandable (all predictions < 50%) |
| Hit Rate | see below | nothing meets the confidence threshold |

**Hit Rate vs. Precision — deliberately different questions.** Precision
uses the standard 0.5 decision threshold: "of everything the model leaned
Over on, how often was it right." Hit Rate instead only looks at
genuinely **confident** selections (`predicted probability >= 0.70` by
default) — "when the model backs a pick with real conviction, how often
is it right." That's the practically relevant question for a system that
only ever surfaces high-confidence picks (Phase 11's Top 10); at the 0.5
threshold the two metrics can coincide by coincidence, but
`test_hit_rate_differs_from_precision_at_default_thresholds` proves they
are computed independently and diverge on data designed to separate them.

**Calibration Error.** A sample-size-weighted mean absolute gap between
each probability band's mean predicted probability and its actual
observed frequency — a version of Expected Calibration Error, restricted
to the ≥50% range this platform actually selects from (see Probability
Bands below). Directly built from the same band breakdown the spec
requires as its own diagnostic.

## Probability bands

Per spec: `50-55, 55-60, 60-65, 65-70, 70-75, 75-80, 80+` (the schema
constant `PROBABILITY_BANDS`, `app/db/models/evaluation.py` — every module
that needs the band list imports it rather than redefining it). For each
band, `compute_probability_band_breakdown` reports predicted probability
(mean), actual frequency, and sample size — this is the calibration
diagnostic the spec calls for. A prediction below 50% is unbanded (`None`)
by design: only "Over" selections are within scope for calibration
banding, an "Under-leaning" prediction isn't a candidate selection.

## Segments (`app/backtest/segments.py`)

Every fold × model_type combination is evaluated **overall** and sliced
by:

- **league** (`segment_value` = league_id as a string)
- **season** (`segment_value` = season_id as a string)
- **probability_band** (only predictions ≥ 50%; still counted in `overall`)
- **home_away** — see below

A segment with zero matching rows is simply omitted, never written as an
empty/null row.

**The home/away segment is an interpretive choice**, called out explicitly
because the spec's "results by ... home/away" instruction was written with
a match-outcome (1X2) model in mind and doesn't map literally onto a
total-goals market — there's no "home side" or "away side" of an
Over/Under bet. Each evaluated fixture is categorized `home_leaning` or
`away_leaning` by comparing that fixture's Poisson
`expected_home_goals` vs `expected_away_goals` (computed for every
evaluation row regardless of which model_type is actually being scored,
purely for this categorization). That answers "did the model expect the
home or away side to contribute more of the total goals" — the closest
sensible analogue to a home/away split for a total-goals model, and it
lets every model_type (including `ml`, which has no expected-goals output
of its own) be sliced the same consistent way.

## Running a backtest

```bash
cd platform/backend
python3 -m app.backtest.cli run
# or a subset of model types:
python3 -m app.backtest.cli run --model-types poisson
```

Requires fixtures with computed features (and, for `ml`, enough history
per fold to train — see Phase 6). Results land in `backtest_results`,
one row per (fold, model_type, segment_type, segment_value); re-running
is idempotent.

## What's still open

- `sportmonks` and `raw_ensemble`/`final` model_types aren't evaluated
  yet — they don't exist until Phase 9 (Sportmonks integration) and
  Phase 8 (ensemble/calibration). `run_walkforward_backtest`'s
  `model_types` parameter is built to extend to them without any change
  to this phase's code.
- No real historical data has been ingested in this session (no live
  Sportmonks token) — every result described above is verified against
  synthetic data with a known, controlled relationship to the label, not
  a real backtest.
