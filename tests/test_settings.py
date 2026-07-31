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
