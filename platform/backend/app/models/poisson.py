"""Poisson baseline model for Over 2.5 goals.

Independent-Poisson approach with attack/defense strength ratios (the
standard simplified football-Poisson formulation; a ratio approximation
of the two-parameter-per-team model Dixon-Coles fits jointly):

Let:
  mu_home = league-wide average goals scored BY HOME teams
          = (by construction) also the league-wide average of goals
            CONCEDED BY AWAY teams, since it's the same underlying numbers
  mu_away = league-wide average goals scored BY AWAY teams
          = also the league-wide average of goals CONCEDED BY HOME teams

For a fixture with home team i, away team j:
  home_attack   = (i's avg goals scored at home)     / mu_home
  away_defense  = (j's avg goals conceded away)       / mu_home   <- normalized
                                                                      against mu_home, NOT mu_away,
                                                                      because "goals j concedes away"
                                                                      is drawn from the same
                                                                      league-wide distribution as
                                                                      "goals home teams score"
  expected_home_goals = mu_home * home_attack * away_defense

  away_attack   = (j's avg goals scored away)         / mu_away
  home_defense  = (i's avg goals conceded at home)    / mu_away   <- normalized against mu_away
                                                                      for the mirror-image reason
  expected_away_goals = mu_away * away_attack * home_defense

  lambda_total = expected_home_goals + expected_away_goals
  P(Over 2.5) = 1 - exp(-lambda_total) * (1 + lambda_total + lambda_total^2 / 2)

(the sum of two independent Poisson variables is itself Poisson with the
summed rate, so treating total goals as Poisson(lambda_total) is valid
here; P(Over 2.5) is exactly P(X >= 3) for X ~ Poisson(lambda_total).)

Team goal rates come from Phase 4's team_features: venue-specific
(`venue_last{W}_*`, i.e. the home team's HOME record / away team's AWAY
record — exactly what this formula needs) with a fallback to
`overall_last{W}_*` if a team has no venue-specific history yet. Returns
None — never a fabricated number — whenever the league baseline or a
team's goal rate isn't available.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_WINDOW = 10
_MIN_LEAGUE_GOALS_AVG = 1e-6  # guards against division by (near) zero


@dataclass(frozen=True)
class PoissonEstimate:
    expected_home_goals: float
    expected_away_goals: float
    lambda_total: float
    probability_over_2_5: float


def poisson_over_2_5_probability(lambda_total: float) -> float:
    if lambda_total < 0:
        raise ValueError("lambda_total must be non-negative")
    return 1.0 - math.exp(-lambda_total) * (1.0 + lambda_total + (lambda_total**2) / 2.0)


def _team_goal_rate(team_features: dict, *, window: int, stat: str) -> float | None:
    """stat: 'goals_scored' or 'goals_conceded'. Prefers this team's
    venue-specific rate (already scoped to its role in the target fixture
    by Phase 4); falls back to its overall rate if no venue-specific
    history exists yet."""
    venue_value = team_features.get(f"venue_last{window}_{stat}")
    if venue_value is not None:
        return venue_value
    return team_features.get(f"overall_last{window}_{stat}")


def estimate_poisson(
    home_team_features: dict,
    away_team_features: dict,
    match_features: dict,
    *,
    window: int = DEFAULT_WINDOW,
) -> PoissonEstimate | None:
    mu_home = match_features.get("league_home_goals_avg")
    mu_away = match_features.get("league_away_goals_avg")
    if not mu_home or not mu_away or mu_home < _MIN_LEAGUE_GOALS_AVG or mu_away < _MIN_LEAGUE_GOALS_AVG:
        return None

    home_scored = _team_goal_rate(home_team_features, window=window, stat="goals_scored")
    home_conceded = _team_goal_rate(home_team_features, window=window, stat="goals_conceded")
    away_scored = _team_goal_rate(away_team_features, window=window, stat="goals_scored")
    away_conceded = _team_goal_rate(away_team_features, window=window, stat="goals_conceded")
    if None in (home_scored, home_conceded, away_scored, away_conceded):
        return None

    home_attack = home_scored / mu_home
    away_defense = away_conceded / mu_home
    expected_home_goals = max(mu_home * home_attack * away_defense, 0.0)

    away_attack = away_scored / mu_away
    home_defense = home_conceded / mu_away
    expected_away_goals = max(mu_away * away_attack * home_defense, 0.0)

    lambda_total = expected_home_goals + expected_away_goals
    probability = poisson_over_2_5_probability(lambda_total)

    return PoissonEstimate(
        expected_home_goals=expected_home_goals,
        expected_away_goals=expected_away_goals,
        lambda_total=lambda_total,
        probability_over_2_5=probability,
    )
