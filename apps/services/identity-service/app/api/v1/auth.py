"""
app/api/v1/auth.py

Account-entry routes: signup, login, tenant selection. Thin adapters
over AuthService — no business logic here, and no exception handling
here either; the RFC 9457 exception handler already owns translating
whatever AuthService raises into a response, so a route just lets it
propagate.
"""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_auth_service
from app.api.mappers import (
    to_authenticated_session_response,
    to_tenant_selection_required_response,
)
from app.api.schemas.auth import (
    AuthenticatedSessionResponse,
    LoginRequest,
    LoginResponseBody,
    SelectTenantRequest,
    SignupRequest,
)
from app.services.auth_models import AuthenticatedSession
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


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
