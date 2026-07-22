"""tests/unit/api/test_auth_dependency.py

Builds a minimal throwaway FastAPI app with one protected route to
test get_current_claims() end to end — including that failures
actually come back in the RFC 9457 shape (register_exception_handlers
is included here deliberately, not just the dependency in isolation).
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth_dependency import get_current_claims
from app.api.dependencies import build_services
from app.api.errors import register_exception_handlers
from app.constants.roles import Role
from app.core.config import Settings
from app.security.jwt import encode_jwt
from app.security.secret_provider import FileSecretProvider
from app.security.token_models import AccessTokenClaims
from scripts.generate_signing_keypair import generate_keypair


def _build_test_app(token_service) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.token_service = token_service

    @app.get("/protected")
    async def _protected_route(claims: AccessTokenClaims = Depends(get_current_claims)):
        return {"user_id": str(claims.user_id), "role": claims.role.value}

    return app


@pytest.fixture
def registry(tmp_path):
    generate_keypair(tmp_path)
    return build_services(Settings(SECRETS_DIR=tmp_path))


@pytest.fixture
def client(registry) -> TestClient:
    return TestClient(_build_test_app(registry.token_service))


class TestGetCurrentClaims:
    @pytest.mark.asyncio
    async def test_valid_token_succeeds(self, client, registry):
        user_id, tenant_id = uuid4(), uuid4()
        access_token = await registry.token_service.issue_access_token(
            user_id=user_id, tenant_id=tenant_id, role=Role.OWNER, permissions_version=0
        )

        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {access_token}"}
        )

        assert response.status_code == 200
        assert response.json()["user_id"] == str(user_id)
        assert response.json()["role"] == "owner"

    def test_missing_header_returns_rfc9457_shape(self, client):
        response = client.get("/protected")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["code"] == "invalid_access_token"

    def test_garbage_token_returns_invalid(self, client):
        response = client.get(
            "/protected", headers={"Authorization": "Bearer not-a-real-token"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"

    def test_non_bearer_scheme_is_rejected(self, client):
        """auto_error=False on HTTPBearer means a non-Bearer scheme
        (e.g. Basic auth) results in no credentials being extracted at
        all — must still produce OUR consistent error shape, not
        FastAPI's default one."""
        response = client.get(
            "/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"

    @pytest.mark.asyncio
    async def test_expired_token_returns_distinct_code(self, client, tmp_path):
        """Expired and invalid must NOT collapse into the same code —
        TokenService already distinguishes them; this dependency must
        preserve that distinction, not redo or lose it.

        Constructed via an independent FileSecretProvider reading the
        SAME physical key files generate_keypair(tmp_path) already
        wrote — not by reaching into TokenService's private key-loading
        method, which would be the same encapsulation violation this
        whole registry design exists to avoid elsewhere."""
        secret_provider = FileSecretProvider(secrets_dir=tmp_path)
        pem = await secret_provider.get_secret(name="jwt_signing_private_key")
        private_key = serialization.load_pem_private_key(pem, password=None)

        now = datetime.now(timezone.utc)
        expired_token = encode_jwt(
            {
                "sub": str(uuid4()),
                "tenant_id": str(uuid4()),
                "role": Role.OWNER.value,
                "permissions_version": 0,
                "token_type": "access",
                "jti": str(uuid4()),
                "iss": "https://identity.flowtona.dev",
                "aud": "flowtona-api",
                "iat": now - timedelta(hours=1),
                "exp": now - timedelta(minutes=1),
            },
            private_key=private_key,
            key_id="flowtona-local-001",
        )

        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "access_token_expired"
