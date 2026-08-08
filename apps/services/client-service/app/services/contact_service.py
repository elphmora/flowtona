"""
app/services/contact_service.py

Entity service for Contact. Same is_primary orchestration pattern as
SiteService — demote-before-promote, composed from
ContactRepository.get_primary() + update() (Decision 4). See
site_service.py's module docstring for why demote-first specifically,
not demote-after.

update_contact() uses simple None-means-unchanged semantics for its
optional parameters, matching ClientService/SiteService — it currently
cannot distinguish "field omitted" from "field explicitly cleared to
null" for site_id/role/email/phone. That distinction belongs at the
API schema layer (e.g. Pydantic's exclude_unset), which doesn't exist
yet. One consequence worth noting rather than treating as accidental:
this means update_contact() can never actually violate the
email-or-phone invariant, since a field is only ever assigned when the
caller explicitly supplied a new (non-null) value — the invariant
can't be broken by this method as currently written, though that's a
side effect of the limitation, not something deliberately relied on.
"""

from uuid import UUID

from app.exceptions.contact import ContactNotFoundError
from app.models.contact import Contact
from app.models.types import utc_now
from app.repositories.contact_repository import ContactRepository
from app.repositories.exceptions import RecordNotFoundError
from app.services.client_service import ClientService


class ContactService:
    def __init__(
        self, contact_repo: ContactRepository, client_service: ClientService
    ) -> None:
        self._contact_repo = contact_repo
        self._client_service = client_service

    async def create_contact(
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
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )

        existing_contacts = await self._contact_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id
        )
        is_first_contact = len(existing_contacts) == 0
        resolved_is_primary = is_first_contact or is_primary

        if resolved_is_primary:
            await self._demote_current_primary(tenant_id=tenant_id, client_id=client_id)

        return await self._contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            site_id=site_id,
            name=name,
            role=role,
            email=email,
            phone=phone,
            is_primary=resolved_is_primary,
        )

    async def get_contact(
        self, *, tenant_id: UUID, client_id: UUID, contact_id: UUID
    ) -> Contact:
        contact = await self._contact_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, contact_id=contact_id
        )
        if contact is None:
            raise ContactNotFoundError()
        return contact

    async def list_contacts(
        self, *, tenant_id: UUID, client_id: UUID, site_id: UUID | None = None
    ) -> list[Contact]:
        return await self._contact_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )

    async def update_contact(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        contact_id: UUID,
        site_id: UUID | None = None,
        name: str | None = None,
        role: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        is_primary: bool | None = None,
    ) -> Contact:
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )
        existing = await self.get_contact(
            tenant_id=tenant_id, client_id=client_id, contact_id=contact_id
        )

        if is_primary is True and not existing.is_primary:
            await self._demote_current_primary(tenant_id=tenant_id, client_id=client_id)

        updated = existing.model_copy()
        if site_id is not None:
            updated.site_id = site_id
        if name is not None:
            updated.name = name
        if role is not None:
            updated.role = role
        if email is not None:
            updated.email = email
        if phone is not None:
            updated.phone = phone
        if is_primary is not None:
            updated.is_primary = is_primary
        updated.updated_at = utc_now()

        try:
            return await self._contact_repo.update(contact=updated)
        except RecordNotFoundError as exc:
            raise ContactNotFoundError() from exc

    async def delete_contact(
        self, *, tenant_id: UUID, client_id: UUID, contact_id: UUID
    ) -> None:
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )
        await self.get_contact(
            tenant_id=tenant_id, client_id=client_id, contact_id=contact_id
        )
        try:
            await self._contact_repo.delete(
                tenant_id=tenant_id, client_id=client_id, contact_id=contact_id
            )
        except RecordNotFoundError as exc:
            raise ContactNotFoundError() from exc

    async def _demote_current_primary(
        self, *, tenant_id: UUID, client_id: UUID
    ) -> None:
        current_primary = await self._contact_repo.get_primary(
            tenant_id=tenant_id, client_id=client_id
        )
        if current_primary is not None:
            current_primary.is_primary = False
            current_primary.updated_at = utc_now()
            await self._contact_repo.update(contact=current_primary)
