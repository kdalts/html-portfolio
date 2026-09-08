import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/football_platform_test",
)


@pytest.fixture(scope="session")
def db_engine():
    """A real Postgres engine for schema/integration tests.

    Skips (rather than fails) dependent tests if no test database is
    reachable, so the pure-unit test suite still runs in environments
    without Postgres available.
    """
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Test database not reachable at {TEST_DATABASE_URL}: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """A session bound to a connection-level transaction that is always
    rolled back at teardown, so tests never need manual cleanup."""
    connection = db_engine.connect()
    trans = connection.begin()
    session_factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        if trans.is_active:
            trans.rollback()
        connection.close()


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
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
    )


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Never let a test actually sleep through backoff delays."""
    calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        calls.append(seconds)

    monkeypatch.setattr("app.integrations.sportmonks.client.time.sleep", fake_sleep)
    return calls
