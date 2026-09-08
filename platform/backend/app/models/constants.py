"""Shared constants for the prediction pipeline. A single model_predictions
row per (fixture_id, model_version) is built up incrementally across
phases (Poisson here, ML in Phase 6, ensemble/calibration in Phase 7/8,
Sportmonks in Phase 9) - they all need to agree on the same version string
to land on the same row rather than each creating their own."""

DEFAULT_MODEL_VERSION = "v1"
