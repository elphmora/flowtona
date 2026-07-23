"""
app/api/v1/invites.py

Invitation creation and acceptance routes. Separate router from
app/api/v1/auth.py — organisation-membership onboarding is a related
but distinct API area from authentication itself.

Thin adapters over AuthService, same as auth.py — no business logic
here, and no exception handling either; the RFC 9457 exception handler
already owns translating whatever AuthService raises into a response.

One exception to "no business logic here": create_invite() verifies
the URL path's tenant_id matches the caller's OWN authenticated
tenant (claims.tenant_id), rejecting a mismatch before ever reaching
AuthService. This is deliberately a route-level check, not something
AuthService itself does — AuthService.create_invite() only verifies
the caller has *an* active membership in the target tenant_id, not
that it's the SAME tenant their current access token was actually
issued for. Without this check, a token issued while scoped to one
tenant could be used to create invitations for a completely different
tenant the same user also happens to belong to, without ever going
through select_tenant() to actually switch context there — a real,
if subtle, scope-escalation gap that's an HTTP-routing concern, not a
domain-service one.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.auth_dependency import get_current_claims
from app.api.dependencies import get_auth_service
from app.api.mappers import (
    to_authenticated_session_response,
    to_invitation_response,
    to_invite_acceptance_response,
)
from app.api.schemas.auth import AuthenticatedSessionResponse
from app.api.schemas.invitations import (
    AcceptInvitationExistingUserRequest,
    AcceptInvitationNewUserRequest,
    CreateInvitationRequest,
    InvitationResponse,
    InviteAcceptanceResponse,
)
from app.exceptions.auth import PermissionDeniedError
from app.security.token_models import AccessTokenClaims
from app.services.auth_service import AuthService

router = APIRouter(tags=["invitations"])


@router.post(
    "/tenants/{tenant_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    tenant_id: UUID,
    body: CreateInvitationRequest,
    claims: AccessTokenClaims = Depends(get_current_claims),
    auth_service: AuthService = Depends(get_auth_service),
) -> InvitationResponse:
    if tenant_id != claims.tenant_id:
        raise PermissionDeniedError()

    invitation = await auth_service.create_invite(
        tenant_id=tenant_id,
        email=body.email,
        role=body.role,
        invited_by_user_id=claims.user_id,
    )
    return to_invitation_response(invitation)


@router.post(
    "/invitations/accept-existing-user",
    response_model=InviteAcceptanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_invite_existing_user(
    body: AcceptInvitationExistingUserRequest,
    claims: AccessTokenClaims = Depends(get_current_claims),
    auth_service: AuthService = Depends(get_auth_service),
) -> InviteAcceptanceResponse:
    """Does NOT mint a new session — accepting an invite and switching
    active tenant are kept as separate actions (see
    InviteAcceptanceResponse's own docstring)."""
    result = await auth_service.accept_invite_existing_user(
        raw_token=body.token, authenticated_user_id=claims.user_id
    )
    return to_invite_acceptance_response(result)


@router.post(
    "/invitations/accept-new-user",
    response_model=AuthenticatedSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_invite_new_user(
    body: AcceptInvitationNewUserRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthenticatedSessionResponse:
    """Public — no authentication required, matching signup(). Unlike
    the existing-user variant, there's no prior session to avoid
    duplicating, so this DOES mint the user's very first session."""
    session = await auth_service.accept_invite_new_user(
        raw_token=body.token,
        password=body.password,
        display_name=body.display_name,
    )
    return to_authenticated_session_response(session)
