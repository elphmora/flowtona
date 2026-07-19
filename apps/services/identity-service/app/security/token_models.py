"""
app/security/token_models.py

Grouped with the auth layer that produces and consumes them — not
app/models/, since these aren't persisted domain entities and are only
meaningful within JWT verification (see each model's own note below).
"""

from uuid import UUID

from pydantic import Field

from app.constants.roles import Role
from app.models.base import DomainModel


class AccessTokenClaims(DomainModel):
    """Decoded, validated claims from a verified access token JWT
    (Decision 4) — what AuthService/API middleware use to know "who is
    this request from" after TokenService.verify_access_token() has
    already verified the token's signature, standard claims, and
    token_type. Never constructed directly from untrusted input.

    jti included even though nothing currently revokes individual
    access tokens by it — provides traceability and supports a future
    deny-list or audit mechanism without a claims-shape migration when
    that's built."""

    user_id: UUID
    tenant_id: UUID
    role: Role
    # ge=0, not ge=1 — 0 is the real initial value for a brand-new
    # TenantMembership, not a placeholder or impossible one.
    permissions_version: int = Field(ge=0)
    jti: UUID


class PreauthTokenClaims(DomainModel):
    """Decoded, validated claims from a verified tenant-selection
    pre-auth token JWT (Decision 3).

    Deliberately minimal — carries only user_id, not a list of the
    user's available tenants/memberships. The tenant-selection step
    should do a FRESH MembershipService.get_memberships_for_user()
    lookup using this user_id, not trust a list embedded in the token
    at login time: if a membership is revoked between login and
    tenant-selection, a fresh lookup catches it; an embedded list
    would be silently stale."""

    user_id: UUID
    jti: UUID
