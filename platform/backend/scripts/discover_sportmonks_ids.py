"""Looks up the real Sportmonks type/market IDs for your subscription and
prints candidates for app/ingestion/sportmonks_reference.py, which ships
with those values as placeholders (Sportmonks assigns them per-account
and they aren't guessable from public docs).

Sportmonks splits its API into several namespaces (football-specific,
core/shared reference data, odds) whose exact base paths vary by plan
and API version, so rather than assume one path, this probes several
plausible candidates for each resource and reports which ones actually
respond - a 404 here just means "wrong path", not "broken".

Run:
    python scripts/discover_sportmonks_ids.py

This only reads from Sportmonks (no database writes) - safe to re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402

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

MARKET_PATH_CANDIDATES = [
    "/v3/odds/markets",
    "/v3/football/odds/markets",
    "/v3/markets",
]
TYPES_PATH_CANDIDATES = [
    "/v3/core/types",
    "/v3/football/core/types",
    "/v3/types",
]


def _probe(client: httpx.Client, token: str, path_candidates: list[str], per_page: int) -> list[dict] | None:
    for path in path_candidates:
        try:
            items: list[dict] = []
            page = 1
            while True:
                response = client.get(path, params={"api_token": token, "per_page": per_page, "page": page})
                if response.status_code == 404:
                    print(f"  {path}: 404 (not this one)")
                    break
                response.raise_for_status()
                payload = response.json()
                items.extend(payload.get("data", []))
                pagination = payload.get("pagination") or {}
                if not pagination.get("has_more"):
                    print(f"  {path}: OK ({len(items)} items)")
                    return items
                page += 1
        except httpx.HTTPStatusError as exc:
            print(f"  {path}: HTTP {exc.response.status_code} ({exc.response.text[:120]})")
        except httpx.HTTPError as exc:
            print(f"  {path}: request failed ({exc})")
    return None


def _search(items: list[dict], keyword_map: dict[str, list[str]]) -> None:
    for constant, keywords in keyword_map.items():
        matches = [
            item for item in items if any(kw in (item.get("name") or "").lower() for kw in keywords)
        ]
        if not matches:
            print(f"  {constant}: no match found")
            continue
        print(f"  {constant}: candidates ->")
        for m in matches[:8]:
            print(f"      id={m.get('id')}  name={m.get('name')!r}")


def main() -> None:
    settings = get_settings()
    origin = urlsplit(settings.sportmonks_base_url)
    root = f"{origin.scheme}://{origin.netloc}"

    with httpx.Client(base_url=root, timeout=settings.sportmonks_timeout_seconds) as client:
        print("Probing odds-markets endpoints...")
        markets = _probe(client, settings.sportmonks_api_token, MARKET_PATH_CANDIDATES, per_page=100)
        if markets:
            print()
            _search(markets, ODDS_MARKET_KEYWORDS)
        else:
            print("  No working odds-markets path found among the candidates tried.")

        print("\nProbing core-types endpoints...")
        types_ = _probe(client, settings.sportmonks_api_token, TYPES_PATH_CANDIDATES, per_page=200)
        if types_:
            print()
            _search(types_, PREDICTION_TYPE_KEYWORDS)
            _search(types_, CORE_TYPE_KEYWORDS)
        else:
            print("  No working core-types path found among the candidates tried.")

    print(
        "\nDouble-check each candidate's exact name before using it - pick the "
        "one that matches what you actually want, then edit "
        "app/ingestion/sportmonks_reference.py by hand."
    )


if __name__ == "__main__":
    main()
