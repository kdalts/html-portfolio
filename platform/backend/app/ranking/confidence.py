"""confidence_score: how much this platform trusts a given
final_probability — deliberately a distinct quantity from probability
itself and from market edge (the platform's core rule: "The system must
distinguish between 1. probability 2. confidence 3. market edge").

confidence_score = data_completeness x league_reliability x model_agreement

- data_completeness: Phase 4's match_features.data_completeness_score —
  how much rolling history actually backed the features.
- league_reliability: Phase 11's league_reliability_score — this
  league's historical track record for the model.
- model_agreement: how closely the available probability sources
  (poisson/ml/sportmonks) agree with each other. Sources that agree
  closely raise confidence; sources that diverge widely lower it. With
  only one source available (no other to corroborate against), agreement
  defaults to SINGLE_SOURCE_AGREEMENT_DEFAULT — a fixed, documented
  penalty for having nothing to cross-check against, rather than either
  extreme (full confidence or zero).

All three factors are multiplicative and each already in [0, 1], so a
single weak dimension pulls the whole score down rather than being
averaged away by the other two.
"""

from __future__ import annotations

MAX_EXPECTED_STD = 0.15  # probabilities routinely disagreeing by more than ~15pts (stdev) signals real uncertainty
SINGLE_SOURCE_AGREEMENT_DEFAULT = 0.7


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute_agreement_factor(available_probabilities: list[float]) -> float:
    if len(available_probabilities) < 2:
        return SINGLE_SOURCE_AGREEMENT_DEFAULT
    mean = sum(available_probabilities) / len(available_probabilities)
    variance = sum((p - mean) ** 2 for p in available_probabilities) / len(available_probabilities)
    std = variance**0.5
    return _clip01(1 - std / MAX_EXPECTED_STD)


def compute_confidence_score(
    *,
    data_completeness_score: float | None,
    league_reliability_score: float | None,
    available_probabilities: list[float],
) -> float:
    completeness = data_completeness_score if data_completeness_score is not None else 0.0
    reliability = league_reliability_score if league_reliability_score is not None else 0.0
    agreement = compute_agreement_factor(available_probabilities)
    return _clip01(completeness * reliability * agreement)
