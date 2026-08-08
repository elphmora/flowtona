"""
app/services/site_service.py

Entity service for Site. Two things live here that don't live in
SiteRepository, by design (client-service-architecture.md Decisions 4,
9; 02-sequence-diagrams.md):

- is_primary orchestration: first-site-auto-primary on create, and
  demote-then-promote composed from SiteRepository.get_primary() +
  update() calls (not a single atomic repository method — that
  boundary was deliberately settled during the Protocol design: the
  repository exposes primitives, the service composes them).

  ORDERING MATTERS: every method here demotes the current primary
  BEFORE creating/promoting the new one, never after. An earlier draft
  of create_site() got this backwards — create the new primary site
  first, demote the old one second — which has a real window where
  get_primary() could return the newly-created site itself (not the
  old one) during that second step, meaning the old primary never
  actually gets demoted and two sites end up simultaneously
  is_primary=True. Demote-first avoids that window entirely: there's
  never a moment where two sites are both flagged primary.

- delete_site()'s full ordering is Decision 9: confirm the client is
  writable (via ClientService, not by touching ClientRepository
  directly), THEN bulk-detach contacts via
  ContactRepository.clear_site_assignment(), THEN delete the site.
  Reversing either step risks a Contact left pointing at a deleted
  Site.
"""

from uuid import UUID

from app.exceptions.site import SiteNotFoundError
from app.models.address import Address
from app.models.site import Site
from app.models.types import utc_now
from app.repositories.contact_repository import ContactRepository
from app.repositories.exceptions import RecordNotFoundError
from app.repositories.site_repository import SiteRepository
from app.services.client_service import ClientService


class SiteService:
    def __init__(
        self,
        site_repo: SiteRepository,
        contact_repo: ContactRepository,
        client_service: ClientService,
    ) -> None:
        self._site_repo = site_repo
        self._contact_repo = contact_repo
        self._client_service = client_service

    async def create_site(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        label: str,
        address: Address,
        is_primary: bool = False,
    ) -> Site:
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )

        existing_sites = await self._site_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id
        )
        is_first_site = len(existing_sites) == 0
        # Decision 4: the client's FIRST site is always auto-primary,
        # regardless of what the caller requested.
        resolved_is_primary = is_first_site or is_primary

        if resolved_is_primary:
            # Demote-first — see module docstring. A no-op when
            # is_first_site is True, since there's nothing to demote.
            await self._demote_current_primary(tenant_id=tenant_id, client_id=client_id)

        return await self._site_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            label=label,
            address=address,
            is_primary=resolved_is_primary,
        )

    async def get_site(
        self, *, tenant_id: UUID, client_id: UUID, site_id: UUID
    ) -> Site:
        site = await self._site_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )
        if site is None:
            raise SiteNotFoundError()
        return site

    async def list_sites(self, *, tenant_id: UUID, client_id: UUID) -> list[Site]:
        return await self._site_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id
        )

    async def update_site(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        site_id: UUID,
        label: str | None = None,
        address: Address | None = None,
        is_primary: bool | None = None,
    ) -> Site:
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )
        existing = await self.get_site(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )

        if is_primary is True and not existing.is_primary:
            # Demote-first, same reasoning as create_site().
            await self._demote_current_primary(tenant_id=tenant_id, client_id=client_id)

        updated = existing.model_copy()
        if label is not None:
            updated.label = label
        if address is not None:
            updated.address = address
        if is_primary is not None:
            updated.is_primary = is_primary
        updated.updated_at = utc_now()

        try:
            return await self._site_repo.update(site=updated)
        except RecordNotFoundError as exc:
            raise SiteNotFoundError() from exc

    async def delete_site(
        self, *, tenant_id: UUID, client_id: UUID, site_id: UUID
    ) -> int:
        """Decision 9's exact ordering. Returns the count of contacts
        detached — a genuine domain fact about the outcome of this
        operation (how many contacts were affected), not a value that
        exists solely to feed site_delete_contact_nulled_total. The
        route layer can use it for that metric later, but that's a
        consumer of this return value, not its reason for existing."""
        await self._client_service.require_writable_client(
            tenant_id=tenant_id, client_id=client_id
        )
        await self.get_site(tenant_id=tenant_id, client_id=client_id, site_id=site_id)

        affected_count = await self._contact_repo.clear_site_assignment(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )
        try:
            await self._site_repo.delete(
                tenant_id=tenant_id, client_id=client_id, site_id=site_id
            )
        except RecordNotFoundError as exc:
            raise SiteNotFoundError() from exc
        return affected_count

    async def _demote_current_primary(
        self, *, tenant_id: UUID, client_id: UUID
    ) -> None:
        current_primary = await self._site_repo.get_primary(
            tenant_id=tenant_id, client_id=client_id
        )
        if current_primary is not None:
            current_primary.is_primary = False
            current_primary.updated_at = utc_now()
            await self._site_repo.update(site=current_primary)
