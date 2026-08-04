import pytest

from edutap.data_provider.settings import Settings


def test_reads_the_prefixed_variables(monkeypatch):
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", "/etc/views.yaml")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "secret")
    settings = Settings()
    assert settings.database_url.get_secret_value().endswith("/db")
    assert str(settings.config_path) == "/etc/views.yaml"


def test_no_secret_is_leaked_by_repr(monkeypatch):
    """Neither the token nor the password inside the database URL may show up.

    `BaseSettings.__repr__` prints every field that is not a `SecretStr` verbatim,
    and a DSN carries the database password in clear text — so the URL is a secret
    just as much as the token is.
    """
    monkeypatch.setenv(
        "EDUTAP_DATA_PROVIDER_DATABASE_URL",
        "postgresql+asyncpg://dbuser:dbpassword@host:5432/db",
    )
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", "/etc/views.yaml")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "secret")
    printed = repr(Settings())
    assert "secret" not in printed
    assert "dbpassword" not in printed


def test_missing_required_settings_fail_loudly(monkeypatch):
    for name in ("DATABASE_URL", "CONFIG_PATH", "API_TOKEN"):
        monkeypatch.delenv(f"EDUTAP_DATA_PROVIDER_{name}", raising=False)
    # Deliberately generic: Settings has no custom exception type of its own, and
    # pinning this to pydantic-settings' internal ValidationError would couple the
    # test to an implementation detail. The contract under test is "fails loudly
    # somehow", not "fails with this specific class".
    with pytest.raises(Exception):  # noqa: B017
        Settings()


def test_an_empty_api_token_is_refused(monkeypatch):
    """A configured token of "" would start a service that can serve nobody.

    The request-time guard in `api.auth` already refuses an empty credential, so
    such a deployment was never *open* — it was silently closed, on every request,
    forever. The defect belongs where it can be seen: at settings load, which
    `create_app` performs while it builds.
    """
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", "/etc/views.yaml")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "")
    # Generic in the class, specific in the message, for the reason given above:
    # what is under test is that it fails and says why, not which class carries it.
    with pytest.raises(Exception, match="must not be empty"):
        Settings()


def test_observability_is_off_when_nothing_is_configured():
    """The default is a service that reports nowhere.

    Every one of the other tests in this suite runs in this state, so if the
    default were anything else they would all be emitting.
    """
    from edutap.data_provider.observability import ObservabilitySettings

    settings = ObservabilitySettings()

    assert settings.sentry_dsn is None
    assert settings.otlp_endpoint is None
    assert settings.pseudonym_salt is None
    assert settings.environment == "production"


def test_the_observability_settings_never_refuse_to_build(monkeypatch):
    """No field is required, on purpose.

    `create_app` reads these *before* it resolves `Settings`, so that a process
    refusing to start is still reported. A required field here would make the
    reporting of a broken configuration itself depend on a working configuration.
    """
    from edutap.data_provider.observability import ObservabilitySettings

    for name in ("DATABASE_URL", "CONFIG_PATH", "API_TOKEN"):
        monkeypatch.delenv(f"EDUTAP_DATA_PROVIDER_{name}", raising=False)

    assert ObservabilitySettings() is not None


def test_the_dsn_and_the_salt_are_secrets(monkeypatch):
    """Neither may appear in a repr, for the reason `database_url` is a secret."""
    from edutap.data_provider.observability import ObservabilitySettings

    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_SENTRY_DSN", "https://public@bugsink.invalid/7")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_PSEUDONYM_SALT", "a-real-salt")

    rendered = repr(ObservabilitySettings())

    assert "public@bugsink.invalid" not in rendered
    assert "a-real-salt" not in rendered
