"""
Thin client for the API-Football v3 REST API, with:
  - on-disk JSON caching (so re-runs / retries don't burn API quota)
  - simple rate limiting (requests/minute)
  - retry with backoff on 429 / 5xx
  - a running call counter so the caller can log/report quota usage

API-Football docs: https://www.api-football.com/documentation-v3
NOTE: endpoint shapes below match the v3 documentation at the time this was
written. If API-Football changes a field name, the affected stat will come
back as None/missing and be reported as "N/A" / a data gap rather than
crashing the whole run -- see team_stats.py / checks.py.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

from config import SETTINGS

log = logging.getLogger("over25.api")


class ApiFootballError(RuntimeError):
    pass


class ApiFootballClient:
    def __init__(self, settings=SETTINGS):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update(settings.api_headers)
        self.cache_dir = Path(settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._min_interval = 60.0 / max(settings.requests_per_minute, 1)
        self._last_call_ts = 0.0
        self.call_count = 0
        self.cache_hits = 0

    # ------------------------------------------------------------------ #
    # Core request plumbing
    # ------------------------------------------------------------------ #
    def _cache_path(self, endpoint: str, params: dict) -> Path:
        key = json.dumps({"endpoint": endpoint, "params": params}, sort_keys=True)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        safe_endpoint = endpoint.strip("/").replace("/", "_")
        return self.cache_dir / f"{safe_endpoint}__{digest}.json"

    def _read_cache(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        age_hours = (time.time() - path.stat().st_mtime) / 3600.0
        if age_hours > self.settings.cache_ttl_hours:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, path: Path, payload: dict) -> None:
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not write cache file %s: %s", path, exc)

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_ts
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)

    def get(self, endpoint: str, params: dict | None = None, use_cache: bool = True) -> dict:
        params = params or {}
        cache_path = self._cache_path(endpoint, params)

        if use_cache:
            cached = self._read_cache(cache_path)
            if cached is not None:
                self.cache_hits += 1
                return cached

        url = f"{self.settings.api_base_url}/{endpoint.lstrip('/')}"
        backoff = 2.0
        last_exc: Exception | None = None

        for attempt in range(5):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=30)
                self._last_call_ts = time.time()
                self.call_count += 1
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("Network error calling %s (attempt %d): %s", endpoint, attempt + 1, exc)
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code == 429 or resp.status_code >= 500:
                log.warning(
                    "API-Football returned %s for %s (attempt %d) -- backing off %.0fs",
                    resp.status_code, endpoint, attempt + 1, backoff,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code != 200:
                raise ApiFootballError(
                    f"API-Football request to {endpoint} failed: HTTP {resp.status_code} - {resp.text[:300]}"
                )

            try:
                data = resp.json()
            except ValueError as exc:
                raise ApiFootballError(f"Non-JSON response from {endpoint}: {exc}") from exc

            errors = data.get("errors")
            if errors:
                # API-Football returns {} for no errors, but a dict/list with
                # content when e.g. the plan doesn't include this endpoint.
                log.warning("API-Football reported errors for %s: %s", endpoint, errors)

            if use_cache:
                self._write_cache(cache_path, data)
            return data

        raise ApiFootballError(f"Giving up on {endpoint} after repeated failures: {last_exc}")

    # ------------------------------------------------------------------ #
    # Endpoint helpers
    # ------------------------------------------------------------------ #
    def fixtures_by_date(self, date_str: str) -> list:
        data = self.get("fixtures", {"date": date_str, "timezone": self.settings.api_timezone})
        return data.get("response", [])

    def standings(self, league_id: int, season: int) -> list:
        data = self.get("standings", {"league": league_id, "season": season})
        response = data.get("response", [])
        if not response:
            return []
        return response[0].get("league", {}).get("standings", [])

    def team_statistics(self, team_id: int, league_id: int, season: int) -> dict:
        data = self.get(
            "teams/statistics",
            {"team": team_id, "league": league_id, "season": season},
        )
        return data.get("response", {}) or {}

    def team_fixtures(self, team_id: int, season: int, last: int | None = None) -> list:
        params = {"team": team_id, "season": season}
        if last:
            params["last"] = last
        data = self.get("fixtures", params)
        return data.get("response", [])

    def head_to_head(self, team1_id: int, team2_id: int, last: int = 3) -> list:
        data = self.get("fixtures/headtohead", {"h2h": f"{team1_id}-{team2_id}", "last": last})
        return data.get("response", [])

    def fixture_statistics(self, fixture_id: int) -> list:
        data = self.get("fixtures/statistics", {"fixture": fixture_id})
        return data.get("response", [])

    def fixture_events(self, fixture_id: int) -> list:
        data = self.get("fixtures/events", {"fixture": fixture_id})
        return data.get("response", [])

    def injuries(self, team_id: int, season: int) -> list:
        data = self.get("injuries", {"team": team_id, "season": season}, use_cache=True)
        return data.get("response", [])

    def league_info(self, league_id: int, season: int) -> dict:
        data = self.get("leagues", {"id": league_id, "season": season})
        response = data.get("response", [])
        return response[0] if response else {}
