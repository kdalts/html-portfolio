"""Resilient client for the Sportmonks Football v3 API.

Design goals for Phase 1:
  - The API token is never hard-coded; it is injected via Settings, which
    itself reads only from the environment / .env.
  - Transient failures (429 rate limiting, 5xx, network errors) are retried
    with exponential backoff, honouring a Retry-After header when present.
  - Authentication failures (401/403) fail fast without retrying.
  - A client-side request budget avoids tripping Sportmonks' own rate limit
    in the first place.
  - Pagination is handled transparently for callers.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Iterator
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.integrations.sportmonks.exceptions import (
    SportmonksAPIError,
    SportmonksAuthError,
    SportmonksRateLimitError,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
AUTH_ERROR_STATUS_CODES = {401, 403}


class SportmonksClient:
    """Thin wrapper around the Sportmonks Football v3 HTTP API."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = httpx.Client(
            base_url=self._settings.sportmonks_base_url,
            timeout=self._settings.sportmonks_timeout_seconds,
            transport=transport,
        )
        self._request_timestamps: deque[float] = deque()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SportmonksClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- rate limiting --------------------------------------------------------

    def _throttle(self) -> None:
        """Block until issuing another request stays within the configured
        client-side requests-per-minute budget, to avoid tripping Sportmonks'
        own rate limiter in the first place."""
        limit = self._settings.sportmonks_requests_per_minute
        if limit <= 0:
            return
        window_seconds = 60.0
        now = time.monotonic()
        while self._request_timestamps and now - self._request_timestamps[0] > window_seconds:
            self._request_timestamps.popleft()
        if len(self._request_timestamps) >= limit:
            sleep_for = window_seconds - (now - self._request_timestamps[0])
            if sleep_for > 0:
                logger.info("Sportmonks client-side rate limit reached; sleeping %.2fs", sleep_for)
                time.sleep(sleep_for)
        self._request_timestamps.append(time.monotonic())

    # -- core request handling -------------------------------------------------

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        request_params["api_token"] = self._settings.sportmonks_api_token

        max_retries = self._settings.sportmonks_max_retries
        backoff_base = self._settings.sportmonks_backoff_base_seconds
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            self._throttle()
            try:
                response = self._client.request(method, path, params=request_params)
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt >= max_retries:
                    raise SportmonksAPIError(f"Network error calling Sportmonks {path}: {exc}") from exc
                sleep_for = backoff_base * (2**attempt)
                logger.warning(
                    "Sportmonks network error on %s (attempt %s/%s): %s",
                    path,
                    attempt + 1,
                    max_retries,
                    exc,
                )
                time.sleep(sleep_for)
                continue

            if response.status_code in AUTH_ERROR_STATUS_CODES:
                raise SportmonksAuthError(
                    f"Sportmonks authentication failed ({response.status_code}) calling {path}. "
                    "Check that SPORTMONKS_API_TOKEN is set and valid."
                )

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt >= max_retries:
                    if response.status_code == 429:
                        raise SportmonksRateLimitError(
                            f"Sportmonks rate limit exceeded calling {path} after {max_retries} retries"
                        )
                    raise SportmonksAPIError(
                        f"Sportmonks returned {response.status_code} calling {path} "
                        f"after {max_retries} retries"
                    )
                sleep_for = self._retry_delay(response, attempt, backoff_base)
                logger.warning(
                    "Sportmonks returned %s on %s (attempt %s/%s); retrying in %.2fs",
                    response.status_code,
                    path,
                    attempt + 1,
                    max_retries,
                    sleep_for,
                )
                time.sleep(sleep_for)
                continue

            if response.status_code >= 400:
                raise SportmonksAPIError(
                    f"Sportmonks returned {response.status_code} calling {path}: {response.text[:500]}"
                )

            try:
                return response.json()
            except ValueError as exc:
                raise SportmonksAPIError(f"Sportmonks returned invalid JSON calling {path}") from exc

        raise SportmonksAPIError(
            f"Sportmonks request to {path} failed after {max_retries} retries"
        ) from last_exc

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int, backoff_base: float) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return backoff_base * (2**attempt)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params)

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Yield every item across all pages of a Sportmonks list endpoint."""
        request_params = dict(params or {})
        page = request_params.get("page", 1)
        while True:
            request_params["page"] = page
            payload = self.get(path, request_params)
            for item in payload.get("data", []):
                yield item
            pagination = payload.get("pagination") or {}
            if not pagination.get("has_more"):
                break
            page += 1

    # -- connection check --------------------------------------------------------

    def test_connection(self) -> bool:
        """Verify the configured API token can authenticate against Sportmonks.

        Raises SportmonksAuthError / SportmonksAPIError / SportmonksRateLimitError
        on failure; returns True only on a genuinely successful call.
        """
        self.get("/leagues", params={"per_page": 1})
        return True

    # -- Phase 1 read endpoints ----------------------------------------------
    # Additional endpoints (fixtures/between, statistics, xG, odds, etc.) are
    # added in later phases alongside the database schema that stores them.

    def get_leagues(self, *, include: str | None = None, per_page: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": per_page}
        if include:
            params["include"] = include
        return list(self.paginate("/leagues", params))

    def get_fixtures_between(
        self,
        start_date: str,
        end_date: str,
        *,
        include: str | None = None,
        per_page: int = 50,
    ) -> list[dict[str, Any]]:
        """start_date / end_date must be 'YYYY-MM-DD' strings."""
        params: dict[str, Any] = {"per_page": per_page}
        if include:
            params["include"] = include
        return list(self.paginate(f"/fixtures/between/{start_date}/{end_date}", params))

    def get_fixture(self, fixture_id: int, *, include: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if include:
            params["include"] = include
        payload = self.get(f"/fixtures/{fixture_id}", params)
        return payload.get("data", {})
