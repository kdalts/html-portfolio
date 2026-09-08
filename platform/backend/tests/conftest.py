import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings() is process-cached; isolate tests from each other."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def dummy_settings() -> Settings:
    return Settings(
        _env_file=None,
        sportmonks_api_token="test-token",
        sportmonks_base_url="https://api.sportmonks.test/v3/football",
        sportmonks_timeout_seconds=1.0,
        sportmonks_max_retries=2,
        sportmonks_backoff_base_seconds=0.0,
        sportmonks_requests_per_minute=0,  # disable client-side throttling in tests
    )


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Never let a test actually sleep through backoff delays."""
    calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr("app.integrations.sportmonks.client.time.sleep", fake_sleep)
    return calls
