"""tests/unit/api/test_system_health.py

Tests for the k8s health probes.
"""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


class TestHealthz:
    def test_returns_200_unconditionally(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestReadyz:
    def test_returns_200_when_keypair_present(self, client):
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    def test_returns_503_when_keypair_missing(self, tmp_path):
        """Deliberately does NOT use the shared conftest fixtures —
        those always generate a keypair first. This test needs an app
        pointed at a genuinely EMPTY secrets directory, to prove the
        probe correctly reports not-ready rather than silently
        succeeding."""
        app = create_app(Settings(SECRETS_DIR=tmp_path))
        with TestClient(app) as broken_client:
            response = broken_client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}


class TestStartupz:
    def test_returns_200_when_keypair_present(self, client):
        response = client.get("/startupz")
        assert response.status_code == 200
        assert response.json() == {"status": "started"}

    def test_returns_503_when_keypair_missing(self, tmp_path):
        app = create_app(Settings(SECRETS_DIR=tmp_path))
        with TestClient(app) as broken_client:
            response = broken_client.get("/startupz")
        assert response.status_code == 503
        assert response.json() == {"status": "not_started"}


class TestProbeConsistency:
    def test_readiness_and_startup_both_fail_when_keypair_missing(self, tmp_path):
        """Both dependency-sensitive probes fail when JWT keys are
        unavailable."""
        app = create_app(Settings(SECRETS_DIR=tmp_path))
        with TestClient(app) as broken_client:
            ready_response = broken_client.get("/readyz")
            startup_response = broken_client.get("/startupz")

        assert ready_response.status_code == 503
        assert startup_response.status_code == 503
        assert ready_response.json() == {"status": "not_ready"}
        assert startup_response.json() == {"status": "not_started"}
