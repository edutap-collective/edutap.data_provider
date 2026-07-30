"""Shared fixtures."""

import pytest

_ENVIRONMENT = (
    "EDUTAP_DATA_PROVIDER_DATABASE_URL",
    "EDUTAP_DATA_PROVIDER_CONFIG_PATH",
    "EDUTAP_DATA_PROVIDER_API_TOKEN",
    "EDUTAP_DATA_PROVIDER_ECHO_SQL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Remove ambient settings and drop cached ones between tests.

    `get_settings`, `get_provider_config` and `get_repository` are lru_cached: without
    clearing them a test would silently run against the previous test's environment,
    and the failure would look like a logic bug rather than a fixture bug.

    `edutap.data_provider.api.dependencies` (Task 9) does not exist yet at this
    point in the build: the import is guarded so this fixture works both now and
    once that module lands. Task 9 can drop the guard once the module is real.

    The guard catches `ImportError`, not the narrower `ModuleNotFoundError`:
    `from package import missing_submodule` raises a plain `ImportError`
    ("cannot import name") when `package` exists but the submodule file does
    not, because Python falls back to an attribute lookup on the already
    imported package before it would ever get to a `ModuleNotFoundError` for
    a genuinely absent top-level module. `ModuleNotFoundError` is a subclass
    of `ImportError`, so this guard also still catches that narrower case.
    """
    for name in _ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    from edutap.data_provider import settings as settings_module

    settings_module.get_settings.cache_clear()

    try:
        from edutap.data_provider.api import dependencies
    except ImportError:
        dependencies = None

    if dependencies is not None:
        dependencies.get_provider_config.cache_clear()
        dependencies.get_repository.cache_clear()

    yield

    settings_module.get_settings.cache_clear()
    if dependencies is not None:
        dependencies.get_provider_config.cache_clear()
        dependencies.get_repository.cache_clear()


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
