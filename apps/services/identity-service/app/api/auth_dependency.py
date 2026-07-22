"""
app/api/auth_dependency.py

FastAPI dependency that extracts and verifies a Bearer access token,
producing AccessTokenClaims — protected routes declare this via
Depends(get_current_claims), the same way they get AuthService via
Depends(get_auth_service).

Uses fastapi.security.HTTPBearer (not a raw Header() parameter) so
protected routes get correct OpenAPI security-scheme documentation and
a working "Authorize" button in the generated Swagger UI — the
standard, idiomatic way to do Bearer auth in FastAPI.

auto_error=False is deliberate and important: HTTPBearer's default
behavior raises FastAPI's own generic HTTPException when the header is
missing or malformed, which would bypass the RFC 9457 exception
handling built specifically to give every error response one
consistent shape. Disabling that lets a missing/malformed header
result in InvalidAccessTokenError instead — going through the same
handler as every other error in this API, not FastAPI's default format.

A missing header and a garbage token are treated identically
(InvalidAccessTokenError) — both represent the same outcome to the
caller ("not properly authenticated"), so there's no need to invent a
separate exception just to distinguish which specific way that
happened, matching the "reuse an existing exception when the semantic
outcome is genuinely the same" pattern already used elsewhere (e.g.
NoActiveMembershipError reused across login() and select_tenant()).

Expired vs. invalid tokens are NOT collapsed here — TokenService.
verify_access_token() already raises the correct, distinct exception
type (ExpiredAccessTokenError vs. InvalidAccessTokenError) depending on
why verification failed; this dependency just lets whichever one it
raises propagate, preserving that distinction rather than needing to
redo it.
"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.dependencies import get_token_service
from app.exceptions.token import InvalidAccessTokenError
from app.security.token_models import AccessTokenClaims
from app.services.token_service import TokenService

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    token_service: TokenService = Depends(get_token_service),
) -> AccessTokenClaims:
    if credentials is None:
        raise InvalidAccessTokenError()
    return await token_service.verify_access_token(token=credentials.credentials)
