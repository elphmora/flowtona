"""
tests/unit/api/system/test_info.py
"""

from app.core.config import settings as default_settings


class TestInfo:
    def test_returns_200(self, client):
        response = client.get("/info")
        assert response.status_code == 200

    def test_has_exactly_the_keys_platform_conventions_9_requires(self, client):
        response = client.get("/info")
        assert set(response.json().keys()) == {
            "service",
            "version",
            "build",
            "git_sha",
            "environment",
        }

    def test_values_match_settings(self, client):
        response = client.get("/info")
        body = response.json()
        assert body["service"] == default_settings.SERVICE_NAME
        assert body["version"] == default_settings.SERVICE_VERSION
        assert body["build"] == default_settings.BUILD_ID
        assert body["git_sha"] == default_settings.GIT_SHA
        assert body["environment"] == default_settings.ENVIRONMENT.value

    def test_does_not_publish_jwks_endpoint(self, client):
        """client-service is a JWKS CONSUMER, not an issuer — unlike
        identity-service, it has nothing to publish at this well-known
        path and must not accidentally expose one."""
        response = client.get("/.well-known/jwks.json")
        assert response.status_code == 404
