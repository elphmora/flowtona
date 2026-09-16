"""
tests/unit/api/test_auth_errors.py

Proves the exact chain this checkpoint exists to establish:
InvalidAccessTokenError -> HTTP 401, application/problem+json,
WWW-Authenticate: Bearer, RFC 9457 body -- against job-service's own
real running app, not inferred from client-service's confirmed
behavior.

Both tests add a throwaway route to a freshly created app instance --
a legitimate way to test cross-cutting auth/error-handling behavior
without needing POST /v1/jobs (not wired up yet) to exist first.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.api.auth_dependency import get_current_claims
from app.exceptions.auth import InvalidAccessTokenError
from app.main import create_app
from app.security.token_verifier import AccessTokenClaims


def test_invalid_access_token_error_produces_correct_401_response() -> None:
    app = create_app()

    test_router = APIRouter()

    @test_router.get("/__test_raises_invalid_token__")
    async def _raise() -> None:
        raise InvalidAccessTokenError()

    app.include_router(test_router)

    with TestClient(app) as client:
        response = client.get("/__test_raises_invalid_token__")

    assert response.status_code == 401
    assert "application/problem+json" in response.headers["content-type"]
    assert response.headers["www-authenticate"] == "Bearer"

    body = response.json()
    assert body["code"] == "invalid_access_token"
    assert body["status"] == 401
    assert body["type"].endswith("/invalid-access-token")
    assert body["instance"] == "/__test_raises_invalid_token__"
    assert body["detail"]
    assert body["request_id"]


def test_non_bearer_auth_scheme_is_rejected() -> None:
    """A claim about HTTPBearer's own real behavior (does it actually
    return None, not raise or pass through, for a non-Bearer scheme),
    not just this codebase's downstream logic -- found missing during
    a post-green architectural review. Exercised through a real
    request against a real protected route, not a direct function
    call, since that's the only way to genuinely verify FastAPI's own
    dependency behaves as relied upon."""
    app = create_app()

    test_router = APIRouter()

    @test_router.get("/__test_requires_auth__")
    async def _protected(
        claims: Annotated[AccessTokenClaims, Depends(get_current_claims)],
    ) -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(test_router)

    with TestClient(app) as client:
        response = client.get(
            "/__test_requires_auth__", headers={"Authorization": "Basic abc123"}
        )

    assert response.status_code == 401
