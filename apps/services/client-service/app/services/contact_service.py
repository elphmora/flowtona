"""
app/services/contact_service.py

Entity service for Contact. Same is_primary orchestration pattern as
SiteService — demote-before-promote, composed from
ContactRepository.get_primary() + update() (Decision 4). See
site_service.py's module docstring for why demote-first specifically,
not demote-after.

Site ownership: create_contact()/update_contact() validate a supplied
site_id actually belongs to this client via SiteService.get_site()
(which already raises SiteNotFoundError for wrong-client/wrong-tenant)
— reusing that existing check rather than reaching into
SiteRepository directly, matching the same service-to-service
orchestration pattern SiteService already uses for ClientService.
Deliberately NOT applied to list_contacts()'s site_id filter — a
well-formed but non-matching site_id there must return an empty list
(01-api-contract.md), not a 404; ownership validation is only for
writes that would actually attach a contact to a site.

update_contact()'s PATCH semantics distinguish three states per
optional field (site_id, role, email, phone), not two:
    UNSET       - caller omitted the field; leave the existing value.
    None        - caller explicitly sent null; clear the existing value.
    real value  - replace the existing value.
This is a real fix, not a style preference: the previous None-means-
omitted-or-clear implementation could never actually clear site_id
(detach a contact from its site via PATCH) or role/email/phone,
because an explicit null was indistinguishable from an omitted field.
The route layer resolves omitted fields into UNSET before calling the
service — this service only receives the already-resolved UNSET/None/
value each parameter should take. name and is_primary don't
need this treatment: name is never legitimately null (Contact.name
isn't nullable in the domain model), and is_primary has no clearable
"null" state of its own — both keep simple None-means-omitted
semantics, matching ClientService/SiteService.

The email-or-phone invariant (Decision 8) is enforced here at the
MERGED-state level for updates, not solely by Pydantic on the request
body — a PATCH clearing email must be checked against what phone will
be AFTER the update is applied, which requires knowing the contact's
existing state, not just what's in this one request.

UNSET is used to distinguish omitted PATCH fields from fields
explicitly set to null. See client-service-architecture.md's Entity &
Convention Clarifications for the full three-state PATCH pattern this
establishes — reusable by any future service with the same need, not
specific to Contact.
"""

from typing import Final, cast
from uuid import UUID

from pydantic import ValidationError

from app.exceptions.contact import (
    ContactNotFoundError,
    ContactRequiresEmailOrPhoneError,
)
from app.metrics.business_metrics import CONTACT_CREATED_TOTAL
from app.models.contact import Contact
from app.models.types import utc_now
from app.repositories.contact_repository import ContactRepository
from app.repositories.exceptions import RecordNotFoundError
from app.services.client_service import ClientService
from app.services.site_service import SiteService


class _UnsetType:
    """Marker type representing an omitted PATCH field."""


UNSET: Final = _UnsetType()


class ContactService:
    def __init__(
        self,
        contact_repo: ContactRepository,
        client_service: ClientService,
        site_service: SiteService,
    ) -> None:
        self._contact_repo = contact_repo
        self._client_service = client_service
        self._site_service = site_service

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
        is_primary: bool | None = None,
    ) -> Contact:
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )
        if site_id is not None:
            await self._site_service.get_site(
                tenant_id=tenant_id, client_id=client_id, site_id=site_id
            )

        existing_contacts = await self._contact_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id
        )
        is_first_contact = len(existing_contacts) == 0
        resolved_is_primary = is_first_contact or is_primary is True

        if resolved_is_primary:
            await self._demote_current_primary(tenant_id=tenant_id, client_id=client_id)

        contact = await self._contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            site_id=site_id,
            name=name,
            role=role,
            email=email,
            phone=phone,
            is_primary=resolved_is_primary,
        )
        CONTACT_CREATED_TOTAL.inc()
        return contact

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
        """site_id here is a FILTER, not an ownership-validated write
        target — deliberately does not call SiteService.get_site().
        01-api-contract.md requires a well-formed but non-matching
        site_id to return an empty list, not 404; calling get_site()
        here would turn that required empty-list behavior into an
        error."""
        return await self._contact_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )

    async def update_contact(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        contact_id: UUID,
        name: str | None = None,
        role: str | None | _UnsetType = UNSET,
        email: str | None | _UnsetType = UNSET,
        phone: str | None | _UnsetType = UNSET,
        site_id: UUID | None | _UnsetType = UNSET,
        is_primary: bool | None = None,
    ) -> Contact:
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )
        existing = await self.get_contact(
            tenant_id=tenant_id, client_id=client_id, contact_id=contact_id
        )

        if site_id is not UNSET and site_id is not None:
            # Explicit cast(): mypy does not narrow custom sentinel
            # types after the UNSET/None checks.
            await self._site_service.get_site(
                tenant_id=tenant_id, client_id=client_id, site_id=cast(UUID, site_id)
            )

        # Contact uses validate_assignment=True. Updating fields one
        # at a time validates intermediate object state rather than
        # the merged final state, so rebuild a new Contact from merged
        # data instead — this also means every validator Contact has,
        # now and in the future, runs against the true final state in
        # one step. model_copy(update=...) was considered and rejected:
        # it skips validation entirely, so a future validator would
        # silently never run during updates.
        merged_data = existing.model_dump()
        if name is not None:
            merged_data["name"] = name
        if role is not UNSET:
            merged_data["role"] = role
        if email is not UNSET:
            merged_data["email"] = email
        if phone is not UNSET:
            merged_data["phone"] = phone
        if site_id is not UNSET:
            merged_data["site_id"] = site_id
        if is_primary is not None:
            merged_data["is_primary"] = is_primary

        try:
            updated = Contact(**merged_data)
        except ValidationError as exc:
            # Contact currently has exactly one model-level validator
            # (email-or-phone), so this translation is accurate today.
            # If a second, unrelated validator is ever added (e.g.
            # phone format), this needs to inspect exc.errors() to
            # raise the right domain exception instead of assuming
            # every ValidationError here means email-or-phone — update
            # this translation at that point, don't leave it silently
            # wrong.
            raise ContactRequiresEmailOrPhoneError() from exc

        if is_primary is True and not existing.is_primary:
            await self._demote_current_primary(tenant_id=tenant_id, client_id=client_id)

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
