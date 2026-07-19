"""
app/services/auth_models.py

Return-value carriers for AuthService's public methods. These
represent orchestration outcomes, not domain entities, so they live
alongside AuthService rather than under models/.

Plain frozen, slotted dataclasses, not Pydantic models — these never
cross an untrusted-input boundary (nothing external constructs them;
AuthService always builds them from already-validated data returned by
other services), so there's no validation for Pydantic to usefully
add. slots=True since these are pure immutable transport objects — no
benefit to allowing arbitrary attributes on something meant to be
constructed once and read.
"""

from dataclasses import dataclass

from app.models.invitation import Invitation
from app.models.membership import TenantMembership
from app.models.tenant import Tenant
from app.models.user import User


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """The outcome of every flow that ends with a fully authenticated
    session: signup, single-membership login, tenant selection,
    refresh, and new-user invite acceptance. Deliberately one shared
    type, not five near-identical ones — they all represent the exact
    same thing: "this user is now authenticated for this tenant."""

    user: User
    tenant: Tenant
    membership: TenantMembership
    access_token: str
    raw_refresh_token: str


@dataclass(frozen=True, slots=True)
class TenantSelectionRequired:
    """Returned when the user has more than one active membership —
    no access or refresh token yet, only a pre-auth token to complete
    tenant selection with."""

    user: User
    preauth_token: str


@dataclass(frozen=True, slots=True)
class InviteAcceptanceResult:
    """Returned by accept_invite_existing_user() — deliberately NOT an
    AuthenticatedSession. An already-authenticated user accepting an
    invite to another tenant should have a membership added, not a
    second refresh-token session silently minted and their active
    tenant context silently switched. The client explicitly selects/
    switches afterward, through the existing tenant-selection path,
    as its own deliberate action."""

    invitation: Invitation
    tenant: Tenant
    membership: TenantMembership
