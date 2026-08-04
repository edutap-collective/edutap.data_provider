"""Shared fixtures."""

import pytest

_ENVIRONMENT = (
    "EDUTAP_DATA_PROVIDER_DATABASE_URL",
    "EDUTAP_DATA_PROVIDER_CONFIG_PATH",
    "EDUTAP_DATA_PROVIDER_API_TOKEN",
    "EDUTAP_DATA_PROVIDER_ECHO_SQL",
    # Without these four a developer with a DSN in their shell would have every
    # test in this suite reporting to a real Bugsink, and the suite would pass.
    "EDUTAP_DATA_PROVIDER_SENTRY_DSN",
    "EDUTAP_DATA_PROVIDER_OTLP_ENDPOINT",
    "EDUTAP_DATA_PROVIDER_PSEUDONYM_SALT",
    "EDUTAP_DATA_PROVIDER_ENVIRONMENT",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Remove ambient settings and drop cached ones between tests.

    `get_settings`, `get_provider_config` and `get_repository` are lru_cached: without
    clearing them a test would silently run against the previous test's environment,
    and the failure would look like a logic bug rather than a fixture bug.
    """
    for name in _ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    from edutap.data_provider import observability
    from edutap.data_provider import settings as settings_module
    from edutap.data_provider.api import dependencies

    settings_module.get_settings.cache_clear()
    dependencies.get_provider_config.cache_clear()
    dependencies.get_repository.cache_clear()
    observability.get_observability_settings.cache_clear()

    yield

    settings_module.get_settings.cache_clear()
    dependencies.get_provider_config.cache_clear()
    dependencies.get_repository.cache_clear()
    observability.get_observability_settings.cache_clear()


MINIMAL_CONFIG = """
views:
  mensapass:
    fields:
      display_name: [STRING, TEXT]
"""


@pytest.fixture
def configured_environment(tmp_path, monkeypatch):
    """Point the process at a minimal, valid configuration; return the file.

    `create_app` resolves the settings and the view configuration while it builds,
    so even a test that only wants an application object needs both to be there.
    The autouse `clean_environment` fixture runs first — pytest orders autouse
    fixtures of a scope before the rest — so this sets what that one just cleared.
    """
    path = tmp_path / "views.yaml"
    path.write_text(MINIMAL_CONFIG)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    return path


@pytest.fixture(scope="session")
def postgres_url():
    """Start a PostgreSQL container and return an asyncpg URL for it."""
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:18-alpine", driver="asyncpg") as container:
        yield container.get_connection_url()


@pytest.fixture
async def engine(postgres_url):
    """An engine on a fresh schema with this package's tables created."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from edutap.data_provider.models import db  # noqa: F401  registers the tables
    from edutap.data_provider.models.base import metadata

    engine = create_async_engine(postgres_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.drop_all)
        await connection.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine):
    """A session factory bound to the test engine."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    return async_sessionmaker(engine, expire_on_commit=False)
