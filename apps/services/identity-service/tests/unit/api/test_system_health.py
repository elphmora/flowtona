"""tests/unit/api/test_system_health.py

Tests for the k8s health probes.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


class TestHealthz:
    def test_returns_200_unconditionally(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestReadyzAndStartupz:
    @pytest.mark.parametrize("path", ["/readyz", "/startupz"])
    def test_returns_200_when_keypair_present(self, client, path):
        response = client.get(path)
        assert response.status_code == 200

    @pytest.mark.parametrize("path", ["/readyz", "/startupz"])
    def test_returns_503_when_keypair_missing(self, path, tmp_path):
        """Deliberately does NOT use the shared conftest fixtures —
        those always generate a keypair first. This test needs an app
        pointed at a genuinely EMPTY secrets directory, to prove the
        probe correctly reports not-ready rather than silently
        succeeding."""
        app = create_app(Settings(SECRETS_DIR=tmp_path))
        with TestClient(app) as broken_client:
            response = broken_client.get(path)
        assert response.status_code == 503
