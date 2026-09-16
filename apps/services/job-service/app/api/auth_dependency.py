"""
app/api/auth_dependency.py

FastAPI dependency extracting and verifying a Bearer access token,
producing AccessTokenClaims. Ported from client-service's own
auth_dependency.py -- identical mechanism, same reasoning.

Uses fastapi.security.HTTPBearer with auto_error=False: lets a
missing/malformed header raise InvalidAccessTokenError and go through
the RFC 9457 handler, instead of FastAPI's own generic HTTPException
bypassing it.

Declares dependencies via typing.Annotated, matching client-service's
own (post-identity-service) convention.
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
