"""Looks up the real Sportmonks type/market IDs for your subscription and
prints candidates for app/ingestion/sportmonks_reference.py, which ships
with those values as placeholders (Sportmonks assigns them per-account
and they aren't guessable from public docs).

Run:
    python scripts/discover_sportmonks_ids.py

This only reads from Sportmonks (no database writes) - safe to re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.integrations.sportmonks.client import SportmonksClient  # noqa: E402

# Keywords to look for in each endpoint's `name` field, mapped to the
# sportmonks_reference.py constant they'd fill in.
ODDS_MARKET_KEYWORDS = {
    "ODDS_MARKET_ID_OVER_UNDER": ["over/under", "goals over/under", "total goals"],
}
PREDICTION_TYPE_KEYWORDS = {
    "PREDICTION_TYPE_ID_OVER_UNDER_2_5": ["over/under", "goals over/under"],
    "PREDICTION_TYPE_ID_BTTS": ["both teams to score", "btts"],
}
CORE_TYPE_KEYWORDS = {
    "STATISTIC_TYPE_IDS['shots_total']": ["shots total"],
    "STATISTIC_TYPE_IDS['shots_on_target']": ["shots on target", "shots on goal"],
    "STATISTIC_TYPE_IDS['corners']": ["corners"],
    "STATISTIC_TYPE_IDS['possession_percentage']": ["ball possession", "possession"],
    "STATISTIC_TYPE_IDS['fouls']": ["fouls"],
    "STATISTIC_TYPE_IDS['yellow_cards']": ["yellowcards", "yellow cards"],
    "STATISTIC_TYPE_IDS['red_cards']": ["redcards", "red cards"],
    "XG_TYPE_ID": ["expected goals", "xg"],
}


def _search(items: list[dict], keyword_map: dict[str, list[str]]) -> None:
    for constant, keywords in keyword_map.items():
        matches = [
            item
            for item in items
            if any(kw in (item.get("name") or "").lower() for kw in keywords)
        ]
        if not matches:
            print(f"  {constant}: no match found")
            continue
        print(f"  {constant}: candidates ->")
        for m in matches[:8]:
            print(f"      id={m.get('id')}  name={m.get('name')!r}")


def main() -> None:
    settings = get_settings()
    with SportmonksClient(settings) as client:
        print("Fetching /odds/markets ...")
        markets = list(client.paginate("/odds/markets", {"per_page": 100}))
        print(f"({len(markets)} markets returned)\n")
        _search(markets, ODDS_MARKET_KEYWORDS)

        print("\nFetching /core/types ...")
        types_ = list(client.paginate("/core/types", {"per_page": 200}))
        print(f"({len(types_)} types returned)\n")
        _search(types_, PREDICTION_TYPE_KEYWORDS)
        _search(types_, CORE_TYPE_KEYWORDS)

    print(
        "\nDouble-check each candidate's exact name before using it - pick the "
        "one that matches what you actually want, then edit "
        "app/ingestion/sportmonks_reference.py by hand."
    )


if __name__ == "__main__":
    main()
