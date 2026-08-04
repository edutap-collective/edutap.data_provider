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

    `hide_parameters=True` is a data-protection setting, not a tuning one. Without
    it, `StatementError.__str__` -- which every SQLAlchemy error wrapping a database
    failure inherits -- appends the bound parameters of the failing statement to its
    message: `[parameters: ('u123456', 'mensapass')]`. The first bound parameter of
    the only statement this service issues is the person. Measured against the real
    application: a dropped pool connection during `/lookup` put that `person_uid`
    into the Sentry event *and* into the exported span's `exception.message`, on the
    one channel `docs/explanation.md` names as remaining -- the text of an exception
    message -- through a message this package does not write and therefore cannot
    phrase carefully. The statement itself still travels, so an operator still sees
    which query failed; only the values bound into it do not. The same flag also
    keeps the parameters out of the engine's own INFO logging, so `echo_sql=true` in
    development no longer prints a person into the console either.
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url.get_secret_value(),
        echo=settings.echo_sql,
        hide_parameters=True,
    )
    return Repository(async_sessionmaker(engine, expire_on_commit=False))
