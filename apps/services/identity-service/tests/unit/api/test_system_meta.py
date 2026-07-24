"""tests/unit/api/test_system_meta.py

Tests for service metadata endpoints.
"""


class TestInfo:
    def test_returns_service_metadata(self, client):
        response = client.get("/info")

        assert response.status_code == 200
        body = response.json()
        assert body["service_name"] == "identity-service"
        assert body["service_version"]
        assert body["environment"]


class TestJwks:
    def test_returns_valid_jwks_structure(self, client):
        response = client.get("/.well-known/jwks.json")

        assert response.status_code == 200
        body = response.json()
        assert "keys" in body
        assert len(body["keys"]) >= 1
        key = body["keys"][0]
        assert key["kty"] == "EC"
        assert key["crv"] == "P-256"
        assert key["alg"] == "ES256"
