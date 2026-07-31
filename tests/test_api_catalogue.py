from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from edutap.data_provider.api.app import create_app
from edutap.data_provider.api.dependencies import get_provider_config
from edutap.data_provider.config import load_config
from edutap.data_provider.settings import Settings, get_settings

CONFIG = """
views:
  mensapass:
    fields:
      display_name: [STRING, TEXT]
    derived:
      pass_valid_until:
        kinds: [STRING, DATETIME]
        rule: add_days(today(), 7)
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    app = create_app()
    app.dependency_overrides[get_provider_config] = lambda: load_config(path)
    return TestClient(app)


def test_catalogue_lists_the_fields_of_a_view(client):
    response = client.get(
        "/catalogue",
        params={"view_type": "mensapass"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert [entry["key"] for entry in response.json()] == ["display_name", "pass_valid_until"]
    assert [entry["derived"] for entry in response.json()] == [False, True]


def test_an_unknown_view_type_is_a_problem_document(client):
    response = client.get(
        "/catalogue",
        params={"view_type": "ghost"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "ghost" in response.json()["detail"]


def test_without_a_token_the_catalogue_is_closed(client):
    assert client.get("/catalogue", params={"view_type": "mensapass"}).status_code == 401


def test_a_wrong_token_is_rejected(client):
    response = client.get(
        "/catalogue",
        params={"view_type": "mensapass"},
        headers={"Authorization": "Bearer nope"},
    )
    assert response.status_code == 401


def test_a_non_ascii_authorization_header_is_rejected(client):
    """A non-ASCII header must be a plain 401, not a 500.

    The header is attacker-controlled and `secrets.compare_digest` raises TypeError
    on a `str` holding non-ASCII characters, so a naive constant-time comparison
    turns a hostile header into a server error. The value is sent as raw bytes
    because that is what a hostile client does — the header arrives at the
    application latin-1 decoded, hence as a `str` with non-ASCII characters.
    """
    response = client.get(
        "/catalogue",
        params={"view_type": "mensapass"},
        headers={"Authorization": "Bearer tökén-ünïcode".encode()},
    )
    assert response.status_code == 401


def test_the_rejection_does_not_distinguish_a_missing_from_a_wrong_token(client):
    """Both failures carry the same body: the response must not be an oracle."""
    missing = client.get("/catalogue", params={"view_type": "mensapass"})
    wrong = client.get(
        "/catalogue",
        params={"view_type": "mensapass"},
        headers={"Authorization": "Bearer nope"},
    )
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json()


def test_another_scheme_is_rejected(client):
    """The token alone, or under a different scheme, is not a bearer credential."""
    for header in ("test-token", "Basic test-token", "Bearer"):
        response = client.get(
            "/catalogue",
            params={"view_type": "mensapass"},
            headers={"Authorization": header},
        )
        assert response.status_code == 401, header


def test_the_scheme_is_matched_case_insensitively(client):
    """RFC 7235 makes the scheme case-insensitive; only the token is a secret."""
    response = client.get(
        "/catalogue",
        params={"view_type": "mensapass"},
        headers={"Authorization": "bearer test-token"},
    )
    assert response.status_code == 200


def test_an_empty_configured_token_authenticates_nobody(client):
    """The guard in `require_token` is a second barrier, not the only one.

    The settings now refuse an empty token outright, so a process configured this
    way never starts — `tests/test_app_skeleton.py` covers that. The guard stays
    because it holds the invariant where it is enforced, without depending on a
    constraint declared in another module: `secrets.compare_digest(b"", b"")` is
    true, so an unguarded comparison would turn an empty expected token into "no
    credential needed".

    `model_construct` skips validation. It is the only way left to reach
    `require_token` with the settings the constraint now forbids — which is exactly
    the state this guard exists for.
    """
    unvalidated = Settings.model_construct(
        database_url=SecretStr("postgresql+asyncpg://u:p@h/db"),
        config_path=Path("views.yaml"),
        api_token=SecretStr(""),
    )
    client.app.dependency_overrides[get_settings] = lambda: unvalidated
    for headers in ({}, {"Authorization": "Bearer "}, {"Authorization": "Bearer"}):
        response = client.get("/catalogue", params={"view_type": "mensapass"}, headers=headers)
        assert response.status_code == 401, headers
