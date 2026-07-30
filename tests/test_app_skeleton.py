from fastapi.testclient import TestClient

from edutap.data_provider.api.app import create_app


def test_healthz_reports_ok():
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version_is_exposed():
    from edutap.data_provider import __version__

    assert __version__
