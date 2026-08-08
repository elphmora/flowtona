"""
app/repositories/in_memory/contact_repository.py

In-memory implementation of ContactRepository (Protocol, Decision 9).

clear_site_assignment() is Decision 9's bulk operation: single pass
over this client's contacts, nulling site_id on every match, inside
one lock acquisition — not a service-layer loop calling update() per
contact. Returns the count affected; SiteService feeds that count into
site_delete_contact_nulled_total, not this repository.

Same tenant/client identity checks and update() guard as
InMemorySiteRepository, for the same reasons.
"""

from uuid import UUID

from app.models.contact import Contact
from app.models.types import utc_now
from app.repositories.exceptions import ImmutableFieldError, RecordNotFoundError
from app.repositories.in_memory.store import InMemoryStore


class InMemoryContactRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        site_id: UUID | None = None,
        name: str,
        role: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        is_primary: bool = False,
    ) -> Contact:
        async with self._store.lock:
            contact = Contact(
                client_id=client_id,
                tenant_id=tenant_id,
                site_id=site_id,
                name=name,
                role=role,
                email=email,
                phone=phone,
                is_primary=is_primary,
            )
            stored = contact.model_copy(deep=True)
            self._store.contacts_by_id[contact.id] = stored
            self._store.contact_ids_by_client.setdefault(client_id, []).append(
                contact.id
            )
            return stored.model_copy(deep=True)

    async def get_by_id(
        self, *, tenant_id: UUID, client_id: UUID, contact_id: UUID
    ) -> Contact | None:
        contact = self._store.contacts_by_id.get(contact_id)
        if (
            contact is None
            or contact.tenant_id != tenant_id
            or contact.client_id != client_id
        ):
            return None
        return contact.model_copy(deep=True)

    async def get_primary(self, *, tenant_id: UUID, client_id: UUID) -> Contact | None:
        for contact_id in self._store.contact_ids_by_client.get(client_id, []):
            contact = self._store.contacts_by_id[contact_id]
            if contact.tenant_id == tenant_id and contact.is_primary:
                return contact.model_copy(deep=True)
        return None

    async def list_by_client(
        self, *, tenant_id: UUID, client_id: UUID, site_id: UUID | None = None
    ) -> list[Contact]:
        results = []
        for contact_id in self._store.contact_ids_by_client.get(client_id, []):
            contact = self._store.contacts_by_id[contact_id]
            if contact.tenant_id != tenant_id:
                continue
            if site_id is not None and contact.site_id != site_id:
                continue
            results.append(contact.model_copy(deep=True))
        return results

    async def update(self, *, contact: Contact) -> Contact:
        async with self._store.lock:
            existing = self._store.contacts_by_id.get(contact.id)
            if existing is None:
                raise RecordNotFoundError(entity="contact", identifier=contact.id)

            if existing.tenant_id != contact.tenant_id:
                raise ImmutableFieldError(
                    entity="contact",
                    field="tenant_id",
                    identifier=contact.id,
                    expected=existing.tenant_id,
                    actual=contact.tenant_id,
                )
            if existing.client_id != contact.client_id:
                raise ImmutableFieldError(
                    entity="contact",
                    field="client_id",
                    identifier=contact.id,
                    expected=existing.client_id,
                    actual=contact.client_id,
                )

            self._store.contacts_by_id[contact.id] = contact.model_copy(deep=True)
            return contact.model_copy(deep=True)

    async def delete(
        self, *, tenant_id: UUID, client_id: UUID, contact_id: UUID
    ) -> None:
        async with self._store.lock:
            existing = self._store.contacts_by_id.get(contact_id)
            if (
                existing is None
                or existing.tenant_id != tenant_id
                or existing.client_id != client_id
            ):
                raise RecordNotFoundError(entity="contact", identifier=contact_id)

            del self._store.contacts_by_id[contact_id]
            ids = self._store.contact_ids_by_client.get(client_id)
            if ids is not None and contact_id in ids:
                ids.remove(contact_id)

    async def clear_site_assignment(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        site_id: UUID,
    ) -> int:
        async with self._store.lock:
            count = 0
            for contact_id in self._store.contact_ids_by_client.get(client_id, []):
                contact = self._store.contacts_by_id[contact_id]
                if contact.tenant_id != tenant_id or contact.site_id != site_id:
                    continue
                data = contact.model_dump()
                data["site_id"] = None
                data["updated_at"] = utc_now()
                updated = Contact(**data)
                self._store.contacts_by_id[contact_id] = updated.model_copy(deep=True)
                count += 1
            return count
