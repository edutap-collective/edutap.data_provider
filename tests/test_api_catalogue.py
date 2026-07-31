import pytest
from fastapi.testclient import TestClient

from edutap.data_provider.api.app import create_app
from edutap.data_provider.api.dependencies import get_provider_config
from edutap.data_provider.config import load_config

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
