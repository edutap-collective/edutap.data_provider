import pytest

from edutap.data_provider.settings import Settings


def test_reads_the_prefixed_variables(monkeypatch):
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", "/etc/views.yaml")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "secret")
    settings = Settings()
    assert settings.database_url.endswith("/db")
    assert str(settings.config_path) == "/etc/views.yaml"


def test_the_token_is_not_leaked_by_repr(monkeypatch):
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", "/etc/views.yaml")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "secret")
    assert "secret" not in repr(Settings())


def test_missing_required_settings_fail_loudly(monkeypatch):
    for name in ("DATABASE_URL", "CONFIG_PATH", "API_TOKEN"):
        monkeypatch.delenv(f"EDUTAP_DATA_PROVIDER_{name}", raising=False)
    # Deliberately generic: Settings has no custom exception type of its own, and
    # pinning this to pydantic-settings' internal ValidationError would couple the
    # test to an implementation detail. The contract under test is "fails loudly
    # somehow", not "fails with this specific class".
    with pytest.raises(Exception):  # noqa: B017
        Settings()
