import traceback

import pytest
from fastapi.testclient import TestClient

from edutap.data_provider.api.app import StartupError, create_app
from edutap.data_provider.api.dependencies import get_provider_config
from edutap.data_provider.settings import get_settings

# `add_days` on a field that declares no DATETIME: refused by the startup type
# check in `validate_config`, not by `load_config`. The two failures reach
# `create_app` on different paths and both must stop it.
CONFIG_THAT_DOES_NOT_VALIDATE = """
views:
  mensapass:
    fields:
      display_name: [STRING, TEXT]
    derived:
      pass_valid_until:
        kinds: [STRING, DATETIME]
        rule: add_days(display_name, 7)
"""


def test_healthz_reports_ok(configured_environment):
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_is_exposed():
    from edutap.data_provider import __version__

    assert __version__


def test_a_missing_setting_stops_the_application_from_being_built():
    """Nothing configured at all: construction fails, rather than the first request.

    Before this, `create_app` touched neither seam — both hang off `Depends` and
    resolve on the first request — so a misconfigured container started, answered
    `/healthz` with `{"status": "ok"}`, passed its deployment health check, and
    failed the first real request as a deliberately opaque 500.
    """
    with pytest.raises(StartupError):
        create_app()


def test_the_startup_failure_names_the_variables_that_are_wrong():
    """Why a container will not start must be answerable from the message alone."""
    with pytest.raises(StartupError) as raised:
        create_app()
    message = str(raised.value)
    for name in ("DATABASE_URL", "CONFIG_PATH", "API_TOKEN"):
        assert f"EDUTAP_DATA_PROVIDER_{name}" in message


def test_the_startup_failure_shows_no_secret(monkeypatch, tmp_path):
    """pydantic's own rendering prints every value that was supplied.

    `ValidationError.errors()[i]["input"]` is the raw settings mapping — the values
    as they were read from the environment, before `SecretStr` ever sees them — and
    `str(ValidationError)` prints it. One missing variable would therefore put the
    API token and the database password of a real deployment into the startup log.
    The rendered traceback, not just the message: that is what an operator reads.
    """
    monkeypatch.setenv(
        "EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:dbpassword@h/db"
    )
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "hunter2")
    with pytest.raises(StartupError) as raised:
        create_app()
    rendered = "".join(traceback.format_exception(raised.value))
    assert "hunter2" not in rendered
    assert "dbpassword" not in rendered
    assert "EDUTAP_DATA_PROVIDER_CONFIG_PATH" in rendered


def test_a_view_configuration_that_is_not_there_stops_the_application(monkeypatch, tmp_path):
    """The settings load; the file they point at does not exist."""
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(tmp_path / "absent.yaml"))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    with pytest.raises(StartupError, match="absent.yaml"):
        create_app()


def test_a_view_configuration_that_does_not_validate_stops_the_application(monkeypatch, tmp_path):
    """The file parses; the startup type check refuses what it says."""
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG_THAT_DOES_NOT_VALIDATE)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    with pytest.raises(StartupError, match="pass_valid_until"):
        create_app()


def test_a_valid_configuration_still_builds_an_application(configured_environment):
    """The check must refuse what is broken and nothing else."""
    app = create_app()
    assert "/catalogue" in app.openapi()["paths"]


def test_the_startup_check_fills_the_cache_the_request_path_reads(configured_environment):
    """One load, not two: the eager call and the dependency are the same object.

    `get_settings` and `get_provider_config` are `lru_cache`d, and `create_app`
    calls the very objects `Depends` resolves. A parallel load would read the file
    twice and could disagree with what the request path then sees.
    """
    create_app()
    assert get_settings.cache_info().currsize == 1
    assert get_provider_config.cache_info().currsize == 1

    get_settings()
    get_provider_config()

    assert get_settings.cache_info().misses == 1
    assert get_provider_config.cache_info().misses == 1


def test_an_empty_api_token_stops_the_application_from_being_built(monkeypatch, tmp_path):
    """The settings constraint and the startup check together: a refusal, visibly.

    On its own, an empty token was refused only per request, silently. On its own,
    the startup check cannot see a value the settings accept.
    """
    path = tmp_path / "views.yaml"
    path.write_text("views:\n  mensapass:\n    fields:\n      display_name: [STRING]\n")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "")
    with pytest.raises(StartupError, match="EDUTAP_DATA_PROVIDER_API_TOKEN"):
        create_app()
