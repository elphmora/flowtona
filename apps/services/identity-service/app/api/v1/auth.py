"""
app/api/v1/auth.py

Account-entry and session routes. Thin adapters over AuthService — no
business logic here, and no exception handling here either; the RFC
9457 exception handler already owns translating whatever AuthService
raises into a response, so a route just lets it propagate.
"""

from fastapi import APIRouter, Depends, status

from app.api.auth_dependency import get_current_claims
from app.api.dependencies import get_auth_service
from app.api.mappers import (
    to_authenticated_session_response,
    to_tenant_selection_required_response,
)
from app.api.schemas.auth import (
    AuthenticatedSessionResponse,
    LoginRequest,
    LoginResponseBody,
    LogoutAllResponse,
    LogoutRequest,
    RefreshRequest,
    SelectTenantRequest,
    SignupRequest,
)
from app.security.token_models import AccessTokenClaims
from app.services.auth_models import AuthenticatedSession
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Account entry ---


@router.post(
    "/signup",
    response_model=AuthenticatedSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def signup(
    body: SignupRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedSessionResponse:
    session = await auth_service.signup(
        email=body.email,
        password=body.password,
        display_name=body.display_name,
        tenant_label=body.tenant_label,
    )
    return to_authenticated_session_response(session)


@router.post("/login", response_model=LoginResponseBody)
async def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> LoginResponseBody:
    """login() can return either outcome over the SAME 200 OK — the
    branch below is the one place a route does more than call the
    service and map the result, since which response type applies
    depends on which one AuthService actually returned."""
    result = await auth_service.login(email=body.email, password=body.password)
    if isinstance(result, AuthenticatedSession):
        return to_authenticated_session_response(result)
    return to_tenant_selection_required_response(result)


@router.post("/select-tenant", response_model=AuthenticatedSessionResponse)
async def select_tenant(
    body: SelectTenantRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedSessionResponse:
    session = await auth_service.select_tenant(
        preauth_token=body.preauth_token, tenant_id=body.tenant_id
    )
    return to_authenticated_session_response(session)


# --- Session lifecycle ---


@router.post("/refresh", response_model=AuthenticatedSessionResponse)
async def refresh(
    body: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedSessionResponse:
    session = await auth_service.refresh(raw_refresh_token=body.refresh_token)
    return to_authenticated_session_response(session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    """204 No Content, not 200 — logout() returns nothing meaningful
    to send back, and it's already idempotent (an unknown or already-
    revoked token is a no-op, not an error), so there's no status
    distinction worth making here either."""
    await auth_service.logout(raw_refresh_token=body.refresh_token)


@router.post("/logout-all-for-tenant", response_model=LogoutAllResponse)
async def logout_all_for_tenant(
    claims: AccessTokenClaims = Depends(get_current_claims),
    auth_service: AuthService = Depends(get_auth_service),
) -> LogoutAllResponse:
    """Revoke every refresh session belonging to the authenticated user
    within the authenticated tenant.

    The authenticated user and tenant are taken from the verified
    access token rather than the request body."""
    revoked_count = await auth_service.logout_all_for_tenant(
        user_id=claims.user_id, tenant_id=claims.tenant_id
    )
    return LogoutAllResponse(revoked_count=revoked_count)
