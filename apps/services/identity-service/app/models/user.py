"""
app/models/user.py

Global identity (ADR Decision 2 refinement, Invariant 1/2). No tenant_id —
a User can hold memberships across multiple tenants (Decision 6).

No email-verification fields here — see app/models/email_verification.py.
A verification token is a short-lived security credential with its own
lifecycle (multiple tokens over time via resend, single-use, revocable);
folding it into this long-lived aggregate would make UserRepository
responsible for credential-token lookup, which is outside its natural
scope. Corrected 2026-07-14, before the initial (wrong) version of this
change was ever committed.

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
