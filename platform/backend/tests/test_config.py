import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_missing_token_raises(monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_blank_token_raises(monkeypatch):
    monkeypatch.delenv("SPORTMONKS_API_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, sportmonks_api_token="   ")


def test_token_read_from_env(monkeypatch):
    monkeypatch.setenv("SPORTMONKS_API_TOKEN", "abc123")
    settings = Settings(_env_file=None)
    assert settings.sportmonks_api_token == "abc123"
    # sensible defaults exist and are not silently overridden
    assert settings.sportmonks_base_url == "https://api.sportmonks.com/v3/football"
    assert settings.sportmonks_max_retries >= 1


def test_token_is_never_hardcoded_in_source():
    import inspect

    from app import core

    source = inspect.getsource(core.config)
    assert "SPORTMONKS_API_TOKEN=" not in source
