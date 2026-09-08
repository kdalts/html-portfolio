"""Application configuration.

Settings are read exclusively from environment variables (optionally via a
local .env file that is never committed). Secrets such as
SPORTMONKS_API_TOKEN must never be hard-coded anywhere in this codebase.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Sportmonks Football API -------------------------------------------------
    sportmonks_api_token: str
    sportmonks_base_url: str = "https://api.sportmonks.com/v3/football"
    sportmonks_timeout_seconds: float = 15.0
    sportmonks_max_retries: int = 5
    sportmonks_backoff_base_seconds: float = 1.0
    sportmonks_requests_per_minute: int = 60

    # --- Database ------------------------------------------------------------------
    database_url: str
    database_echo: bool = False

    @field_validator("sportmonks_api_token")
    @classmethod
    def _token_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(
                "SPORTMONKS_API_TOKEN must be set (via environment variable or .env) "
                "and must not be blank."
            )
        return value

    @field_validator("database_url")
    @classmethod
    def _database_url_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("DATABASE_URL must be set (via environment variable or .env) and must not be blank.")
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Cached so the .env file is parsed once per process; tests that need a
    fresh read should call get_settings.cache_clear() first.
    """
    return Settings()
