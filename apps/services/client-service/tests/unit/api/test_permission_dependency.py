"""
tests/unit/api/test_permission_dependency.py

Builds a minimal throwaway FastAPI app with routes gated by
require_permission(...) to test the full chain end to end: Bearer
token -> get_current_claims() -> permission check -> route body.
Route definitions use app.constants.permissions' CLIENTS_READ/
CLIENTS_WRITE, exactly as real client-service routes should — this is
the concrete case those constants exist to make a typo-proof NameError
instead of a silent runtime deny.
"""

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers
from app.api.permission_dependency import require_permission
from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.security.token_verifier import AccessTokenClaims, TokenVerifier
from tests.unit.auth_fixtures import make_token


def _build_test_app(token_verifier: TokenVerifier) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.token_verifier = token_verifier

    @app.get("/clients")
    async def _list_clients(
        claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_READ))],
    ) -> dict:
        return {"ok": True}

    @app.post("/clients")
    async def _create_client(
        claims: Annotated[
            AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))
        ],
    ) -> dict:
        return {"ok": True}

    return app


class TestRequirePermission:
    def test_route_succeeds_when_permission_present(self, token_verifier, keypair):
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        token = make_token(private_key, permissions=["clients:read"])

        response = client.get("/clients", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200

    def test_route_rejected_when_permission_absent(self, token_verifier, keypair):
        """A technician-shaped token (read-only) hitting a write-gated
        route — the exact real-world case client-service Decision 3
        exists for."""
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        token = make_token(private_key, permissions=["clients:read"])

        response = client.post("/clients", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_permission"

    def test_route_rejected_when_permissions_empty(self, token_verifier, keypair):
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        token = make_token(private_key, permissions=[])

        response = client.get("/clients", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_permission"

    def test_invalid_token_rejected_before_permission_check(self, token_verifier):
        """An invalid token must fail with invalid_access_token (401),
        not insufficient_permission (403) — auth is checked strictly
        before permission, never the reverse. get_current_claims() is
        a Depends() of require_permission()'s own inner check, so
        this proves that dependency ordering actually holds at the
        real FastAPI resolution layer, not just by reading the code."""
        client = TestClient(_build_test_app(token_verifier))

        response = client.get(
            "/clients", headers={"Authorization": "Bearer not-a-real-token"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"

    def test_write_route_succeeds_with_write_permission(self, token_verifier, keypair):
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        token = make_token(private_key, permissions=["clients:read", "clients:write"])

        response = client.post("/clients", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200

    def test_unrelated_permission_does_not_satisfy_the_check(
        self, token_verifier, keypair
    ):
        """A token carrying permissions belonging to another service's
        domain (Amendment 4's additive-evolution case) must not
        accidentally satisfy a clients:read/clients:write check just
        because the token itself was otherwise valid."""
        client = TestClient(_build_test_app(token_verifier))
        private_key, _public_key = keypair
        token = make_token(private_key, permissions=["jobs:write", "invoices:approve"])

        response = client.get("/clients", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 403
