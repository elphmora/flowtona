"""
tests/unit/api/test_auth_dependency.py

Builds a minimal throwaway FastAPI app with one protected route to
test get_current_claims() end to end — including that failures
actually come back in the RFC 9457 shape (register_exception_handlers
is included here deliberately, not just the dependency in isolation).
Matches identity-service's own test_auth_dependency.py pattern. Real
ES256 signing and a real local JWKS server (tests/conftest.py) — no
mocked crypto or network layer.

Not a Platform Conventions §8 "integration test" — that term is
reserved for tests using the real (not hand-assembled) create_app(),
which doesn't exist yet. This uses TestClient and real dependency
resolution against a throwaway app instead, matching identity-
service's own equivalent file, which lives under tests/unit/ too.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth_dependency import get_current_claims
from app.api.errors import register_exception_handlers
from app.security.token_verifier import AccessTokenClaims, TokenVerifier
from tests.unit.auth_fixtures import make_token


def _build_test_app(token_verifier: TokenVerifier) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.token_verifier = token_verifier

    @app.get("/protected")
    async def _protected_route(
        claims: Annotated[AccessTokenClaims, Depends(get_current_claims)],
    ) -> dict:
        return {"sub": str(claims.sub), "tenant_id": str(claims.tenant_id)}

    return app


class TestGetCurrentClaims:
    def test_valid_token_succeeds(self, token_verifier, keypair):
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        sub, tenant_id = uuid4(), uuid4()
        token = make_token(private_key, sub=str(sub), tenant_id=str(tenant_id))

        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.json()["sub"] == str(sub)
        assert response.json()["tenant_id"] == str(tenant_id)

    def test_missing_header_returns_rfc9457_shape(self, token_verifier):
        client = TestClient(_build_test_app(token_verifier))

        response = client.get("/protected")

        assert response.status_code == 401
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["code"] == "invalid_access_token"
        assert response.headers["www-authenticate"] == "Bearer"

    def test_garbage_token_returns_invalid(self, token_verifier):
        client = TestClient(_build_test_app(token_verifier))

        response = client.get(
            "/protected", headers={"Authorization": "Bearer not-a-real-token"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"
        assert response.headers["www-authenticate"] == "Bearer"

    def test_non_bearer_scheme_is_rejected(self, token_verifier):
        """auto_error=False on HTTPBearer means a non-Bearer scheme
        (e.g. Basic auth) results in no credentials being extracted at
        all — must still produce OUR consistent error shape, not
        FastAPI's default one."""
        client = TestClient(_build_test_app(token_verifier))

        response = client.get(
            "/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"

    def test_expired_token_returns_invalid(self, token_verifier, keypair):
        """client-service's verifier deliberately does NOT distinguish
        expired from otherwise-invalid (token_verifier.py's own
        docstring) — both collapse to invalid_access_token, unlike
        identity-service's own distinct expired/invalid split. This
        confirms that collapse holds true at the actual HTTP boundary,
        not only inside TokenVerifier.verify() in isolation."""
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        now = datetime.now(timezone.utc)
        expired_token = make_token(
            private_key, iat=now - timedelta(hours=1), exp=now - timedelta(minutes=1)
        )

        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"

    def test_wrong_issuer_returns_invalid(self, token_verifier, keypair):
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        token = make_token(private_key, iss="https://not-identity-service.example")

        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"

    def test_token_type_not_access_returns_invalid(self, token_verifier, keypair):
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        token = make_token(private_key, token_type="preauth")

        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"


class TestGetTokenVerifierDefensiveCheck:
    def test_missing_token_verifier_on_app_state_raises_sanitized_500(self, keypair):
        """A FastAPI app built WITHOUT app.state.token_verifier set —
        the exact misconfiguration get_token_verifier()'s defensive
        check exists to catch. Proves two things together: an opaque
        AttributeError does not leak, and the global unexpected-error
        handler sanitizes the RuntimeError to a controlled RFC 9457
        500 response. This is a fallback safety net, not a substitute
        for a real startup/lifespan test — once main.py exists, a
        separate test should prove startup itself fails fast instead
        of ever reaching a point where a request could observe this."""
        app = FastAPI()
        register_exception_handlers(app)
        # Deliberately NOT setting app.state.token_verifier here.

        @app.get("/protected")
        async def _protected_route(
            claims: Annotated[AccessTokenClaims, Depends(get_current_claims)],
        ) -> dict:
            return {"sub": str(claims.sub)}

        client = TestClient(app, raise_server_exceptions=False)
        private_key, _public_key = keypair
        token = make_token(private_key)

        response = client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 500
        assert response.json()["code"] == "internal_server_error"
