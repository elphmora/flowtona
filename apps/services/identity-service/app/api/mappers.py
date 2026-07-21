"""
app/api/mappers.py

Converts AuthService's domain objects and result dataclasses into the
HTTP response schemas in app/api/schemas/auth.py. Centralized here so
routes producing an AuthenticatedSession (signup, login, select-tenant)
share one conversion instead of duplicating it.

Only the two top-level functions are public — _to_user_response() and
friends are implementation details of the higher-level mapping. Kept
private for a smaller public surface; promote individually if another
mapper genuinely needs to reuse one later.
"""

from app.api.schemas.auth import (
    AuthenticatedSessionResponse,
    MembershipResponse,
    TenantResponse,
    TenantSelectionRequiredResponse,
    UserResponse,
)
from app.models.membership import TenantMembership
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_models import AuthenticatedSession, TenantSelectionRequired


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified,
    )


def _to_tenant_response(tenant: Tenant) -> TenantResponse:
    return TenantResponse(id=tenant.id, tenant_label=tenant.tenant_label)


def _to_membership_response(membership: TenantMembership) -> MembershipResponse:
    return MembershipResponse(
        role=membership.role, permissions_version=membership.permissions_version
    )


def to_authenticated_session_response(
    session: AuthenticatedSession,
) -> AuthenticatedSessionResponse:
    return AuthenticatedSessionResponse(
        user=_to_user_response(session.user),
        tenant=_to_tenant_response(session.tenant),
        membership=_to_membership_response(session.membership),
        access_token=session.access_token,
        refresh_token=session.raw_refresh_token,
    )


def to_tenant_selection_required_response(
    result: TenantSelectionRequired,
) -> TenantSelectionRequiredResponse:
    return TenantSelectionRequiredResponse(
        user=_to_user_response(result.user),
        preauth_token=result.preauth_token,
    )
