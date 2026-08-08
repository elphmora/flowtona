"""
app/security/token_models.py

Grouped with the auth layer that produces and consumes them — not
app/models/, since these aren't persisted domain entities and are only
meaningful within JWT verification (see each model's own note below).
"""

from uuid import UUID

from pydantic import Field

from app.constants.permissions import Permission
from app.constants.roles import Role
from app.models.base import DomainModel


class AccessTokenClaims(DomainModel):
    """Decoded, validated claims from a verified access token JWT
    (Decision 4) — what AuthService/API middleware use to know "who is
    this request from" after TokenService.verify_access_token() has
    already verified the token's signature, standard claims, and
    token_type. Never constructed directly from untrusted input.

    permissions is the resolved effective permission set at issuance
    time (PermissionService.effective_permissions(), computed by
    AuthService before calling issue_access_token() — TokenService
    itself has no opinion on authorization policy, see its own module
    docstring). This is why permissions_version exists alongside it,
    not instead of it: permissions is a point-in-time snapshot that can
    go stale if the underlying policy changes mid-session (e.g.
    verify_email() lifting the soft gate); permissions_version is what
    lets a caller detect that staleness without needing to decode and
    compare the claim itself.

    jti included even though nothing currently revokes individual
    access tokens by it — provides traceability and supports a future
    deny-list or audit mechanism without a claims-shape migration when
    that's built."""

    user_id: UUID
    tenant_id: UUID
    role: Role
    permissions: frozenset[Permission]
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
