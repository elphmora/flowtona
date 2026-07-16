"""
app/repositories/in_memory/tenant_repository.py

In-memory implementation of TenantRepository (Protocol, Decision 9).

No uniqueness rule on tenant_label — none is decided anywhere, and
inventing one here wasn't asked for. Multiple tenants can share the same
display label; it's an onboarding convenience string (Decision 1), not
an identifier.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.models.tenant import Tenant
from app.repositories.in_memory.store import InMemoryIdentityStore


class InMemoryTenantRepository:
    def __init__(self, store: InMemoryIdentityStore) -> None:
        self._store = store

    async def create(self, *, tenant_label: str) -> Tenant:
        async with self._store.lock:
            tenant = Tenant(
                tenant_label=tenant_label,
                created_at=datetime.now(timezone.utc),
            )
            stored = tenant.model_copy(deep=True)
            self._store.tenants_by_id[tenant.id] = stored
            return stored.model_copy(deep=True)

    async def get_by_id(self, *, tenant_id: UUID) -> Tenant | None:
        tenant = self._store.tenants_by_id.get(tenant_id)
        return tenant.model_copy(deep=True) if tenant else None
