import pytest
from fastapi.testclient import TestClient

from edutap.data_provider.api.app import create_app
from edutap.data_provider.api.dependencies import get_provider_config, get_repository
from edutap.data_provider.config import load_config

CONFIG = """
constants:
  open_ended: 9999-12-31
views:
  mensapass:
    fields:
      display_name: [STRING, TEXT]
      student_role_valid_until: [STRING, DATETIME]
    derived:
      pass_valid_until:
        kinds: [STRING, DATETIME]
        rule: min(add_days(today(), 7), coalesce(student_role_valid_until, open_ended))
"""

ROW = {
    "display_name": "A. Doe",
    "student_role_valid_until": "2026-08-02",
    "internal_note": "not in the catalogue",
}

# A value no producer should have written, but one a real database can hold: the
# field is declared DATETIME, so `rules._as_date` refuses it at read time. Startup
# validation cannot see this — it type-checks the rule, never the rows.
ROW_WITH_UNPARSABLE_DATE = {
    "display_name": "A. Doe",
    "student_role_valid_until": "02.08.2026",
}


class FakeRepository:
    def __init__(self, row):
        self._row = row

    async def person_view(self, person_uid, view_type):
        return self._row if person_uid == "a@lmu.de" else None


def build_client(tmp_path, monkeypatch, row, raise_server_exceptions=True):
    """Build a TestClient serving `row` as the only known person view."""
    path = tmp_path / "views.yaml"
    path.write_text(CONFIG)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    app = create_app()
    app.dependency_overrides[get_provider_config] = lambda: load_config(path)
    app.dependency_overrides[get_repository] = lambda: FakeRepository(row)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


@pytest.fixture
def client(tmp_path, monkeypatch):
    return build_client(tmp_path, monkeypatch, ROW)


@pytest.fixture
def client_with_unparsable_stored_date(tmp_path, monkeypatch):
    """A client whose row stores a German-formatted date in a DATETIME field.

    `raise_server_exceptions=False` makes TestClient behave like the deployed
    server: an unhandled exception becomes a response instead of being re-raised
    into the test. That is the only way to assert on what a consumer receives.
    """
    return build_client(
        tmp_path, monkeypatch, ROW_WITH_UNPARSABLE_DATE, raise_server_exceptions=False
    )


def post(client, body):
    return client.post("/lookup", json=body, headers={"Authorization": "Bearer test-token"})


def test_returns_exactly_the_requested_fields(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": ["display_name"]},
    )
    assert response.status_code == 200
    assert response.json() == {"display_name": "A. Doe"}


def test_a_derived_field_is_computed_at_read_time(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": ["pass_valid_until"]},
    )
    # S105: bandit's hardcoded-password heuristic fires because the underscore-separated
    # words of "pass_valid_until" include "pass". It is a wallet-pass validity date, not
    # a password. Same false positive as the S106 per-file ignore for tests/test_models.py.
    assert response.json()["pass_valid_until"] == "2026-08-02"  # noqa: S105


def test_fields_outside_the_catalogue_are_an_error(client):
    response = post(
        client,
        {"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": ["internal_note"]},
    )
    assert response.status_code == 400
    assert "internal_note" in response.json()["detail"]


def test_an_unknown_person_is_a_not_found_problem(client):
    response = post(
        client,
        {"person_uid": "nobody@lmu.de", "view_type": "mensapass", "fields": ["display_name"]},
    )
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_an_empty_field_is_absent_rather_than_null(client):
    response = post(
        client,
        {
            "person_uid": "a@lmu.de",
            "view_type": "mensapass",
            "fields": ["display_name", "student_role_valid_until"],
        },
    )
    assert set(response.json()) == {"display_name", "student_role_valid_until"}


def test_a_rule_failing_on_stored_data_is_still_a_problem_document(
    client_with_unparsable_stored_date,
):
    response = post(
        client_with_unparsable_stored_date,
        {"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": ["pass_valid_until"]},
    )
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert set(body) >= {"title", "status", "detail"}
    assert body["status"] == 500
    assert "pass_valid_until" in body["detail"]
    assert "mensapass" in body["detail"]
    # The detail reaches the consumer verbatim: it must not carry the stored value.
    assert "02.08.2026" not in body["detail"]
