"""Wiring. Tests override these two seams."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ..config import ProviderConfig, load_config
from ..repository import Repository
from ..settings import get_settings
from ..validation import validate_config


@lru_cache
def get_provider_config() -> ProviderConfig:
    """Load and validate the view configuration once per process."""
    config = load_config(get_settings().config_path)
    validate_config(config)
    return config


@lru_cache
def get_repository() -> Repository:
    """Build the repository against the configured database.

    `create_async_engine` does not connect: the pool opens its first connection
    when a session first executes a statement. Building the repository therefore
    stays free of I/O, which is what lets the catalogue tests leave this seam
    un-overridden while pointing `database_url` at a host that does not resolve.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url.get_secret_value(), echo=settings.echo_sql)
    return Repository(async_sessionmaker(engine, expire_on_commit=False))
