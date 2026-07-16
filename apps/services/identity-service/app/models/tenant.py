"""
app/models/tenant.py

Root entity (ADR Decision 2 refinement, Invariant 11). No tenant_id field —
a tenant doesn't belong to itself, it's identified by its own id.

Deliberately minimal per Decision 1 / Invariant 8: identity-service never
stores tenant business data (company name, billing, address). tenant_label
is a temporary onboarding display label only — canonical business profile
is deferred to a future org-service.

No status field yet (deferred 2026-07-12) — same reasoning as User: a
real feature eventually (tenant closed/suspended), but not yet anchored
to an existing invariant or decision. Add when actually needed.
"""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from app.models.base import DomainModel


class Tenant(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_label: str
    created_at: datetime
