"""
app/repositories/tenant_repository.py

Protocol contract for Tenant persistence (Decision 9). Tenant is a root
entity, not tenant-owned (ADR Decision 2 refinement, Invariant 11) — it
has no tenant_id of its own, and every repository method here is scoped
by the tenant's own id, not by any other tenant_id.

Deliberately minimal surface — Decision 1 means identity-service only
ever creates and reads a Tenant's id + tenant_label. There is no update()
here: nothing currently changes on a Tenant post-creation (no top-level
tenant CRUD exists in 01-api-contract.md — see the scaffold-restructure
notes on why tenants.py was deliberately not added as a route file).
"""

from typing import Protocol
from uuid import UUID

from app.models.tenant import Tenant


class TenantRepository(Protocol):
    async def create(self, *, tenant_label: str) -> Tenant:
        """Create a new tenant.

        Used by the signup workflow, which must preserve all-or-nothing
        behaviour across tenant creation and the owner's first
        TenantMembership (Invariant 11) — this repository persists a
        Tenant on its own and makes no atomicity guarantee across that
        second write; that's an application transaction / unit-of-work
        responsibility, not something one repository method can promise
        by itself.
        """
        ...

    async def get_by_id(self, *, tenant_id: UUID) -> Tenant | None: ...
