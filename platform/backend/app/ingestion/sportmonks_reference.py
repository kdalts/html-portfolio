"""Sportmonks taxonomy IDs (statistic type IDs, prediction market type IDs,
odds market IDs) used to interpret the generic `type_id`/`market_id`-keyed
arrays Sportmonks returns for fixture statistics, predictions, and odds.

Filled in from this account's own /v3/core/types and /v3/odds/markets
reference endpoints (see scripts/discover_sportmonks_ids.py) - these are
account-specific, not guessable from public docs, and a different
Sportmonks account could have different IDs.

The mapping *mechanism* (app/ingestion/mappers.py) is fully implemented
and tested against these IDs as opaque values — nothing about it assumes
particular numbers, so updating this file is the only change needed if
they ever need to change.
"""

# Fixture `statistics` include: our match_statistics column name -> type_id.
# (Keyed by stat name, not type_id, so that every stat gets its own
# placeholder slot instead of colliding on a single `None` dict key.)
STATISTIC_TYPE_IDS: dict[str, int | None] = {
    "shots_total": 42,  # "Shots Total"
    "shots_on_target": 86,  # "Shots On Target"
    "corners": 34,  # "Corners"
    "big_chances_created": None,  # no matching /v3/core/types entry found
    "possession_percentage": 45,  # "Ball Possession %"
    "fouls": 56,  # "Fouls"
    "yellow_cards": 84,  # "Yellowcards"
    "red_cards": 83,  # "Redcards"
}

# Fixture `statistics` include: the type_id whose value is expected goals (xG).
XG_TYPE_ID: int | None = 5304  # "Expected Goals (xG)"

# Fixture `predictions` include: type_id for the Over/Under 2.5 goals market,
# and (optionally) the Both Teams To Score market.
PREDICTION_TYPE_ID_OVER_UNDER_2_5: int | None = 235  # "Over/Under 2.5 Probability"
PREDICTION_TYPE_ID_BTTS: int | None = 231  # "Both Teams To Score Probability"

# Fixture `odds` include: market_id for the Over/Under goals market (paired
# with each odds row's own "total" field, e.g. "2.5", to select the line).
ODDS_MARKET_ID_OVER_UNDER: int | None = 80  # "Goals Over/Under"
