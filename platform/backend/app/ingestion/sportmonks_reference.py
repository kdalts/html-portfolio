"""Sportmonks taxonomy IDs (statistic type IDs, prediction market type IDs,
odds market IDs) used to interpret the generic `type_id`/`market_id`-keyed
arrays Sportmonks returns for fixture statistics, predictions, and odds.

*** These specific integer values are PLACEHOLDERS (None). ***

Sportmonks assigns these IDs per your subscription/plan and they are not
guessable from the public docs alone. Before Phase 9 (Sportmonks model
integration) or Phase 10 (odds/edge) can rely on match_statistics,
match_xg, sportmonks_predictions, or odds being populated with the right
numbers, fetch the authoritative IDs for your account from Sportmonks'
reference endpoints (commonly `/core/types` for statistic/prediction type
IDs and `/odds/markets` for odds market IDs) and fill them in here.

The mapping *mechanism* (app/ingestion/mappers.py) is fully implemented
and tested against these IDs as opaque values — nothing about it assumes
particular numbers, so updating this file is the only change needed once
the real IDs are known.
"""

# Fixture `statistics` include: our match_statistics column name -> type_id.
# (Keyed by stat name, not type_id, so that every stat gets its own
# placeholder slot instead of colliding on a single `None` dict key.)
STATISTIC_TYPE_IDS: dict[str, int | None] = {
    "shots_total": None,
    "shots_on_target": None,
    "corners": None,
    "big_chances_created": None,
    "possession_percentage": None,
    "fouls": None,
    "yellow_cards": None,
    "red_cards": None,
}

# Fixture `statistics` include: the type_id whose value is expected goals (xG).
XG_TYPE_ID: int | None = None

# Fixture `predictions` include: type_id for the Over/Under 2.5 goals market,
# and (optionally) the Both Teams To Score market.
PREDICTION_TYPE_ID_OVER_UNDER_2_5: int | None = None
PREDICTION_TYPE_ID_BTTS: int | None = None

# Fixture `odds` include: market_id for the Over/Under goals market (paired
# with each odds row's own "total" field, e.g. "2.5", to select the line).
ODDS_MARKET_ID_OVER_UNDER: int | None = None
