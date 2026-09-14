"""
tests/unit/api/system/test_info.py
"""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_info_returns_service_identity() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/info")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "job-service"
    assert set(body.keys()) == {"service", "version", "build", "git_sha", "environment"}


def test_info_reflects_the_settings_supplied_to_create_app() -> None:
    """Regression test for a real bug: an earlier draft's GET /info
    constructed its own fresh Settings() independently of whatever
    settings create_app() was actually given, so a caller supplying a
    custom Settings instance would see FastAPI's own title/version
    reflect it while GET /info silently reported different (default)
    values instead. This test fails immediately if that regresses."""
    custom_settings = Settings(SERVICE_NAME="test-job-service", SERVICE_VERSION="99.0")
    with TestClient(create_app(settings=custom_settings)) as client:
        response = client.get("/info")
    body = response.json()
    assert body["service"] == "test-job-service"
    assert body["version"] == "99.0"
