"""Application factory."""

from fastapi import APIRouter, FastAPI
from pydantic import ValidationError

from ..config import ConfigError
from ..settings import Settings, get_settings
from .dependencies import get_provider_config
from .errors import install_error_handlers
from .routers import router

# What an operator reads when the process refuses to come up. Both halves name the
# subject first — settings or view configuration — because those are two different
# files to go and look at.
_SETTINGS_FAILED = "The service cannot start: its settings are unusable."
_CONFIG_FAILED = "The service cannot start: the view configuration is unusable."
_WHERE_TO_LOOK = (
    "Set these in the environment or in a .env file next to the process. No value is "
    "shown above on purpose: the settings carry the API token and the database password."
)


class StartupError(RuntimeError):
    """The process cannot start because its configuration is unusable."""


health_router = APIRouter()


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Report that the process is up.

    Answering at all already carries information: `create_app` resolves the settings
    and the view configuration, so a process that exists is a process whose
    configuration loaded. It still says nothing about the database — nothing here
    opens a connection — so this is liveness, not readiness.
    """
    return {"status": "ok"}


def _describe(error: ValidationError) -> str:
    """Name the environment variables that are wrong, and nothing else.

    Only `loc` and `msg` of each pydantic error are used, deliberately. Both
    `str(ValidationError)` and each error's `input` carry the *raw* settings mapping
    — every value that was supplied, as it was read, before `SecretStr` ever sees it
    — so one missing variable would print the API token and the database password of
    a real deployment into its startup log.
    """
    prefix = Settings.model_config.get("env_prefix", "")
    lines = [
        f"  {prefix}{'.'.join(str(part) for part in problem['loc']).upper()}: {problem['msg']}"
        for problem in error.errors()
    ]
    return "\n".join([_SETTINGS_FAILED, "", *lines, "", _WHERE_TO_LOOK])


def _load_configuration() -> None:
    """Resolve the settings and the view configuration, here and now.

    This is what makes "validated once at startup" true. Both seams hang off
    `Depends` and would otherwise resolve on the *first request*: a misconfigured
    container would start, answer `/healthz` with `{"status": "ok"}`, satisfy a
    health-check-based deployment, and fail the first real request as a deliberately
    opaque 500 — opaque because the blanket handler must not leak stored data.

    It calls the very objects `Depends` resolves, not copies of them. Both are
    `lru_cache`d, so this is one load that the request path then reads, rather than
    a second parallel one that could disagree with it.
    """
    try:
        get_settings()
    except ValidationError as error:
        # `from None`, unlike the branch below: the pydantic error must not be part
        # of the rendered traceback, because printing it is exactly the leak that
        # `_describe` exists to avoid.
        raise StartupError(_describe(error)) from None
    try:
        get_provider_config()
    except ConfigError as error:
        # `from error`: a ConfigError's message is one this package wrote for an
        # operator, so chaining it costs nothing and keeps the origin in the trace.
        raise StartupError(f"{_CONFIG_FAILED}\n\n  {error}") from error


def create_app() -> FastAPI:
    """Build the FastAPI application, or refuse to build a misconfigured one."""
    _load_configuration()
    app = FastAPI(title="eduTAP data provider", version="0.1.0")
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(router)
    return app
