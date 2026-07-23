"""
app/api/schemas/invitations.py

HTTP request/response schemas for invitation creation and acceptance.
Kept in a separate module from schemas/auth.py — organisation-
membership onboarding is a related but distinct API area from
authentication itself, matching the same reasoning behind giving
invitations their own router (app/api/v1/invites.py) rather than
continuing to grow auth.py.
"""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator

from app.constants.roles import Role
from app.models.invitation import InvitationStatus

from .auth import MembershipResponse, TenantResponse


def _reject_blank_password(value: str) -> str:
    """Reject passwords consisting entirely of whitespace, without
    modifying legitimate password content. Duplicated from
    schemas/auth.py rather than imported — that function is named as
    module-private (leading underscore), and this small, self-
    contained rule is cheaper to repeat than to cross that boundary."""
    if not value.strip():
        raise ValueError("must not be entirely whitespace")
    return value


# --- Shared response projections ---


class InvitationResponse(BaseModel):
    id: UUID
    email: EmailStr
    role: Role
    status: InvitationStatus


class InviteAcceptanceResponse(BaseModel):
    """Genuinely different from AuthenticatedSessionResponse, not a
    variant of it — accepting an invite as an existing user
    deliberately does NOT mint a session (see AuthService's own
    InviteAcceptanceResult docstring: accepting an invite and switching
    active tenant are kept as separate actions)."""

    invitation: InvitationResponse
    tenant: TenantResponse
    membership: MembershipResponse


# --- Request bodies ---
#
# tenant_id and invited_by_user_id are deliberately NOT fields here —
# tenant_id comes from the URL path (/v1/tenants/{tenant_id}/invitations),
# invited_by_user_id from the authenticated caller's verified access
# token. Neither should ever be client-supplied body content.


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: Role


class AcceptInvitationExistingUserRequest(BaseModel):
    """Requires an authenticated caller (authenticated_user_id comes
    from claims) — a genuinely different route than the new-user
    variant below, not a branch within one route."""

    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AcceptInvitationNewUserRequest(BaseModel):
    """Deliberately does NOT require authentication — this is how a
    brand-new person joins in the first place."""

    token: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    password: str = Field(min_length=8, max_length=256)
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]

    _validate_password = field_validator("password")(_reject_blank_password)
