"""
app/repositories/contact_repository.py

Protocol contract for Contact persistence (Decision 9 / Platform
Conventions §4). site_id is nullable throughout, matching
app/models/contact.py.

clear_site_assignment() is Decision 9's exact, locked method: a single
bulk operation, not a load-then-iterate-then-save loop, called by
SiteService before the corresponding Site is deleted.

get_primary() is a plain lookup primitive, same reasoning as
SiteRepository.get_primary() — is_primary orchestration lives in
ContactService, not here.
"""

from typing import Protocol
from uuid import UUID

from app.models.contact import Contact


class ContactRepository(Protocol):
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
        """Create a new contact. is_primary is passed through as
        already resolved by ContactService."""
        ...

    async def get_by_id(
        self, *, tenant_id: UUID, client_id: UUID, contact_id: UUID
    ) -> Contact | None: ...

    async def get_primary(self, *, tenant_id: UUID, client_id: UUID) -> Contact | None:
        """The contact currently holding is_primary=True for this
        client, if any (Invariant 2). A lookup primitive for
        ContactService to compose into the demote/promote workflow."""
        ...

    async def list_by_client(
        self, *, tenant_id: UUID, client_id: UUID, site_id: UUID | None = None
    ) -> list[Contact]:
        """Contacts for one client, optionally filtered to one site. A
        site_id matching nothing returns an empty list, not an error
        (01-api-contract.md) — this method's normal empty-list return
        already gives that behaviour."""
        ...

    async def update(self, *, contact: Contact) -> Contact:
        """Persist changes to an existing contact — any field,
        including is_primary."""
        ...

    async def delete(
        self, *, tenant_id: UUID, client_id: UUID, contact_id: UUID
    ) -> None: ...

    async def clear_site_assignment(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        site_id: UUID,
    ) -> int:
        """Set site_id to None on every Contact matching this site
        (Decision 9). Single bulk operation. Returns the count
        affected."""
        ...
