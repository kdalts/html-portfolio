import httpx
import pytest

from app.integrations.sportmonks.client import SportmonksClient
from app.integrations.sportmonks.exceptions import (
    SportmonksAPIError,
    SportmonksAuthError,
    SportmonksRateLimitError,
)


def _client(dummy_settings, handler) -> SportmonksClient:
    transport = httpx.MockTransport(handler)
    return SportmonksClient(settings=dummy_settings, transport=transport)


def test_api_token_sent_as_query_param_and_never_in_url_path(dummy_settings):
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"data": [{"id": 1, "name": "Premier League"}]})

    client = _client(dummy_settings, handler)
    client.get_leagues()

    assert len(seen_requests) == 1
    req = seen_requests[0]
    assert req.url.params["api_token"] == "test-token"
    assert "test-token" not in req.url.path


def test_get_leagues_returns_data(dummy_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": 8, "name": "Premier League"}]})

    client = _client(dummy_settings, handler)
    leagues = client.get_leagues()

    assert leagues == [{"id": 8, "name": "Premier League"}]


def test_pagination_collects_all_pages(dummy_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(
                200,
                json={"data": [{"id": 1}, {"id": 2}], "pagination": {"has_more": True}},
            )
        return httpx.Response(
            200,
            json={"data": [{"id": 3}], "pagination": {"has_more": False}},
        )

    client = _client(dummy_settings, handler)
    items = list(client.paginate("/leagues"))

    assert [item["id"] for item in items] == [1, 2, 3]


def test_auth_error_fails_fast_without_retry(dummy_settings):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"message": "Unauthorized"})

    client = _client(dummy_settings, handler)
    with pytest.raises(SportmonksAuthError):
        client.get_leagues()

    assert call_count == 1  # no retries on auth failure


def test_rate_limit_retries_then_succeeds(dummy_settings, _no_real_sleep):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "Too many requests"})
        return httpx.Response(200, json={"data": [{"id": 1}]})

    client = _client(dummy_settings, handler)
    leagues = client.get_leagues()

    assert leagues == [{"id": 1}]
    assert call_count == 2
    assert len(_no_real_sleep) == 1  # slept once, honouring Retry-After


def test_rate_limit_exhausted_raises(dummy_settings, _no_real_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Too many requests"})

    client = _client(dummy_settings, handler)
    with pytest.raises(SportmonksRateLimitError):
        client.get_leagues()

    # dummy_settings.sportmonks_max_retries == 2 -> 3 total attempts
    assert len(_no_real_sleep) == 2


def test_server_error_retries_then_raises_api_error(dummy_settings, _no_real_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "Service unavailable"})

    client = _client(dummy_settings, handler)
    with pytest.raises(SportmonksAPIError):
        client.get_leagues()


def test_network_error_retries_then_raises(dummy_settings, _no_real_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(dummy_settings, handler)
    with pytest.raises(SportmonksAPIError):
        client.get_leagues()


def test_client_error_4xx_raises_api_error_without_retry(dummy_settings, _no_real_sleep):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(404, json={"message": "Not found"})

    client = _client(dummy_settings, handler)
    with pytest.raises(SportmonksAPIError):
        client.get_fixture(999999)

    assert call_count == 1


def test_test_connection_success(dummy_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/leagues")
        return httpx.Response(200, json={"data": [{"id": 1}]})

    client = _client(dummy_settings, handler)
    assert client.test_connection() is True


def test_test_connection_bad_token(dummy_settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    client = _client(dummy_settings, handler)
    with pytest.raises(SportmonksAuthError):
        client.test_connection()
