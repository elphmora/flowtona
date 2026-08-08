"""
app/repositories/in_memory/client_repository.py

In-memory implementation of ClientRepository (Protocol, Decision 9).

Every read and write checks tenant_id against the stored record, not
just the record's own id — a client_id alone is never sufficient to
fetch or mutate a record; cross-tenant isolation is enforced here as
the final guard (Decision 2 / Platform Conventions §5), not only
trusted from the caller.

update() rejects a tenant_id change (identity-defining field, same
reasoning as identity-service's MembershipRepository.update()) and
raises RecordArchivedError if the stored record is ARCHIVED (Decision
5) — this is the repository-level final guard for that invariant.

archive() is idempotent: archiving an already-archived client returns
it unchanged rather than raising, matching 01-api-contract.md's DELETE
semantics. State reconstructed via model_dump() + constructor, not
model_copy(update=...), so validators re-run — same convention as every
identity-service repository with lifecycle transitions.
"""

from datetime import datetime
from uuid import UUID

from app.models.client import Client
from app.models.enums import ClientStatus, ClientType
from app.repositories.client_repository import ClientPage
from app.repositories.exceptions import (
    ImmutableFieldError,
    RecordArchivedError,
    RecordNotFoundError,
)
from app.repositories.in_memory.store import InMemoryStore


class InMemoryClientRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        tenant_id: UUID,
        name: str,
        client_type: ClientType,
    ) -> Client:
        async with self._store.lock:
            client = Client(tenant_id=tenant_id, name=name, client_type=client_type)
            stored = client.model_copy(deep=True)
            self._store.clients_by_id[client.id] = stored
            self._store.client_ids_by_tenant.setdefault(tenant_id, []).append(client.id)
            return stored.model_copy(deep=True)

    async def get_by_id(self, *, tenant_id: UUID, client_id: UUID) -> Client | None:
        client = self._store.clients_by_id.get(client_id)
        if client is None or client.tenant_id != tenant_id:
            return None
        return client.model_copy(deep=True)

    async def list_by_tenant(
        self,
        *,
        tenant_id: UUID,
        name: str | None = None,
        status: ClientStatus | None = None,
        client_type: ClientType | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ClientPage:
        ids = self._store.client_ids_by_tenant.get(tenant_id, [])
        candidates = [self._store.clients_by_id[i] for i in ids]

        if name is not None:
            needle = name.lower()
            candidates = [c for c in candidates if needle in c.name.lower()]
        if status is not None:
            candidates = [c for c in candidates if c.status == status]
        if client_type is not None:
            candidates = [c for c in candidates if c.client_type == client_type]

        total = len(candidates)
        page = candidates[offset : offset + limit]
        return ClientPage(items=[c.model_copy(deep=True) for c in page], total=total)

    async def update(self, *, client: Client) -> Client:
        async with self._store.lock:
            existing = self._store.clients_by_id.get(client.id)
            if existing is None:
                raise RecordNotFoundError(entity="client", identifier=client.id)

            if existing.tenant_id != client.tenant_id:
                raise ImmutableFieldError(
                    entity="client",
                    field="tenant_id",
                    identifier=client.id,
                    expected=existing.tenant_id,
                    actual=client.tenant_id,
                )

            if existing.status == ClientStatus.ARCHIVED:
                raise RecordArchivedError(entity="client", identifier=client.id)

            self._store.clients_by_id[client.id] = client.model_copy(deep=True)
            return client.model_copy(deep=True)

    async def archive(
        self, *, tenant_id: UUID, client_id: UUID, archived_at: datetime
    ) -> Client:
        async with self._store.lock:
            existing = self._store.clients_by_id.get(client_id)
            if existing is None or existing.tenant_id != tenant_id:
                raise RecordNotFoundError(entity="client", identifier=client_id)

            if existing.status == ClientStatus.ARCHIVED:
                return existing.model_copy(deep=True)

            data = existing.model_dump()
            data["status"] = ClientStatus.ARCHIVED
            data["updated_at"] = archived_at
            updated = Client(**data)

            self._store.clients_by_id[client_id] = updated.model_copy(deep=True)
            return updated.model_copy(deep=True)
