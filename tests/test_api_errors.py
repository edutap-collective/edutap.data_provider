import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edutap.data_provider.api.app import create_app
from edutap.data_provider.api.dependencies import get_provider_config, get_repository
from edutap.data_provider.api.errors import ProblemError, install_error_handlers
from edutap.data_provider.config import load_config

# `lt` has no date-forwarding signature and no date arguments, so `validate_config`
# never inspects the kinds of its operands: this configuration passes startup
# validation unchanged.
CONFIG = """
views:
  comparison:
    fields:
      a: [STRING]
      b: [STRING]
    derived:
      a_is_earlier:
        kinds: [STRING]
        rule: lt(a, b)
"""

# Nothing constrains what a producer actually writes under a STRING-declared field.
# Comparing these two raises TypeError inside `evaluate` — not a RuleError, so the
# route's narrow `except RuleError` does not see it.
ROW = {"a": "abc", "b": 5}

# The stored value must never reach the consumer: an arbitrary exception's message
# can quote personal data, unlike a detail we write ourselves.
STORED_VALUE = "abc"


class FakeRepository:
    def __init__(self, row):
        self._row = row

    async def person_view(self, person_uid, view_type):
        return self._row if person_uid == "a@lmu.de" else None


def build_client(tmp_path, monkeypatch, raise_server_exceptions=False):
    """Build a TestClient over a view whose rule fails with a plain TypeError.

    `raise_server_exceptions=False` makes TestClient behave like the deployed
    server: an unhandled exception becomes a response instead of being re-raised
    into the test. That is the only way to assert on what a consumer receives.
    """
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    app = create_app()
    app.dependency_overrides[get_provider_config] = lambda: load_config(path)
    app.dependency_overrides[get_repository] = lambda: FakeRepository(ROW)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def client(tmp_path, monkeypatch):
    return build_client(tmp_path, monkeypatch)


def post(client, body):
    return client.post("/lookup", json=body, headers={"Authorization": "Bearer test-token"})


def test_an_unexpected_exception_is_still_a_problem_document(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "comparison", "fields": ["a_is_earlier"]},
    )
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert set(body) >= {"title", "status", "detail"}
    assert body["status"] == 500


def test_an_unexpected_exception_leaks_nothing_about_the_stored_data(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "comparison", "fields": ["a_is_earlier"]},
    )
    rendered = response.text
    assert STORED_VALUE not in rendered
    # Neither the exception's own message nor its type name reaches the consumer.
    assert "TypeError" not in rendered
    assert "not supported between instances" not in rendered
    assert "Traceback" not in rendered


def test_an_unexpected_exception_still_reaches_the_server(tmp_path, monkeypatch):
    """ServerErrorMiddleware re-raises after the handler, so the server logs it.

    A blanket handler that swallowed the exception would trade a broken contract
    for a lost traceback. `raise_server_exceptions=True` — the TestClient default —
    surfaces exactly what a real server sees after the response has been sent.
    """
    client = build_client(tmp_path, monkeypatch, raise_server_exceptions=True)
    with pytest.raises(TypeError):
        post(
            client,
            {"person_uid": "a@lmu.de", "view_type": "comparison", "fields": ["a_is_earlier"]},
        )


def test_a_problem_error_keeps_its_own_document(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "nonexistent", "fields": ["a"]},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["title"] == "Unknown view type"


def test_the_blanket_handler_does_not_shadow_a_deliberate_problem_error():
    """The two handlers live in different middleware layers; prove they stay apart."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/deliberate")
    async def deliberate() -> None:
        raise ProblemError(418, "Deliberate", "Written by us, meant for the consumer.")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/deliberate")
    assert response.status_code == 418
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "title": "Deliberate",
        "status": 418,
        "detail": "Written by us, meant for the consumer.",
    }
