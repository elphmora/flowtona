"""
app/models/user.py

Global identity (ADR Decision 2 refinement, Invariant 1/2). No tenant_id —
a User can hold memberships across multiple tenants (Decision 6).

No status field yet (deferred 2026-07-12) — global account
suspend/disable is a real feature eventually, but nothing in the ADR
depends on it today the way TenantMembership.status is already required
by existing invariants. Add when a real need arises, not speculatively.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import EmailStr, Field

from app.models.base import DomainModel


class User(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    email: EmailStr
    password_hash: str
    display_name: str
    email_verified: bool = False
    created_at: datetime
    updated_at: datetime | None = None
