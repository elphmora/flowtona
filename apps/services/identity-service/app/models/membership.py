"""
app/models/membership.py

Tenant-owned entity (ADR Decision 2 refinement) — carries tenant_id.
Represents one user's relationship to one tenant (Decision 6: a user may
hold multiple memberships, one per tenant, with one active tenant per
token at a time).

permissions_version lives HERE, not on User — authorization is tenant-
scoped (a role change in tenant A must not imply tenant B's permissions
changed). It increments per the rule in 01-api-contract.md: role changed,
the role->permission mapping updated, membership revoked, email
verification lifting the soft gate, or account suspension.

MembershipStatus matters for permission resolution: a suspended/revoked
membership resolves to no effective permissions regardless of role — that
logic lives in services/permission_service.py, not here.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from app.constants.roles import Role
from app.models.base import DomainModel


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class TenantMembership(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    tenant_id: UUID
    role: Role
    status: MembershipStatus = MembershipStatus.ACTIVE
    permissions_version: int = 0
    created_at: datetime
    updated_at: datetime | None = None
