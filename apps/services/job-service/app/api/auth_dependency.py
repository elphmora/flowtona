"""
app/api/auth_dependency.py

FastAPI dependency extracting and verifying a Bearer access token,
producing AccessTokenClaims. Ported from client-service's own
auth_dependency.py -- identical mechanism, same reasoning.

Uses fastapi.security.HTTPBearer with auto_error=False: lets a
missing/malformed header raise InvalidAccessTokenError and go through
the RFC 9457 handler, instead of FastAPI's own generic HTTPException
bypassing it.

get_access_token() -- added during POST /v1/jobs's review. An earlier
version of the route used BearerCredentials directly (typed
HTTPAuthorizationCredentials | None) plus `assert credentials is not
None`, relying on require_permission(...)'s own get_current_claims
call having already rejected the None case first. That's an implicit
coupling: the type says "might be None," the route architecture
depends on a sibling dependency's ordering to make that untrue. This
function establishes its own independent guarantee instead -- it
raises InvalidAccessTokenError itself if credentials are missing,
so its return type can honestly be `str`, never `str | None`, correct
even if used alone on some future route with no require_permission(...)
alongside it.
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
    rather than a request-domain exception. app/main.py's lifespan
    handler attaches it before any request reaches this dependency --
    if this ever fires, that attachment step itself is broken."""
    verifier = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise RuntimeError(
            "TokenVerifier has not been initialised on app.state. "
            "Check app/main.py's lifespan handler."
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


async def get_access_token(credentials: BearerCredentials) -> str:
    """The raw bearer token, required and never None -- for callers
    that need to forward the original credential (e.g. Client Service
    calls per Amendment 7) rather than the verified AccessTokenClaims.
    Establishes its own guarantee independently of get_current_claims;
    see module docstring."""
    if credentials is None:
        raise InvalidAccessTokenError()
    return credentials.credentials
