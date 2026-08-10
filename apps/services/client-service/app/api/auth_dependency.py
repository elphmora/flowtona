"""
app/api/auth_dependency.py

FastAPI dependency extracting and verifying a Bearer access token,
producing AccessTokenClaims — protected routes declare this via
Depends(get_current_claims), matching identity-service's own
convention even though client-service verifies via JWKS rather than
issuing tokens itself.

Uses fastapi.security.HTTPBearer with auto_error=False, same reasoning
as identity-service: lets a missing/malformed header raise
InvalidAccessTokenError and go through the RFC 9457 handler, instead
of FastAPI's own generic HTTPException bypassing it.

Declares dependencies via typing.Annotated (BearerCredentials,
TokenVerifierDependency), NOT via Depends(...) in the parameter default
position — a deliberate divergence from identity-service's own
auth_dependency.py, which predates this convention. Annotated is
FastAPI's own recommended style since 0.95+: it avoids putting a
non-optional dependency marker in the "default value" slot, and lets a
dependency type be defined once and reused across every route/
dependency that needs it, rather than re-writing Depends(...) at each
call site. The underlying behavior is identical either way — this is
purely a declaration-style improvement, not a semantic one.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.exceptions.auth import InvalidAccessTokenError
from app.security.token_verifier import AccessTokenClaims, TokenVerifier

_bearer_scheme = HTTPBearer(auto_error=False)

BearerCredentials = Annotated[
    HTTPAuthorizationCredentials | None,
    Depends(_bearer_scheme),
]


def get_token_verifier(request: Request) -> TokenVerifier:
    """Return the process-scoped TokenVerifier from app.state.

    A missing verifier indicates an application bootstrap/configuration
    failure, not an authentication failure, so it raises RuntimeError
    rather than a request-domain exception. The global unexpected-error
    handler (app/api/errors.py) may sanitize that failure to HTTP 500
    if it's encountered during request processing — that's a fallback
    safety net, not the intended detection point; the real fix is
    proving at application startup that TokenVerifier was constructed
    before any request is served (once main.py exists)."""
    verifier = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise RuntimeError(
            "TokenVerifier has not been initialised on app.state. "
            "Ensure the application's startup/lifespan handler "
            "attaches it before any request reaches this dependency."
        )
    return verifier


TokenVerifierDependency = Annotated[
    TokenVerifier,
    Depends(get_token_verifier),
]


async def get_current_claims(
    credentials: BearerCredentials,
    token_verifier: TokenVerifierDependency,
) -> AccessTokenClaims:
    if credentials is None:
        raise InvalidAccessTokenError()
    return token_verifier.verify(credentials.credentials)
