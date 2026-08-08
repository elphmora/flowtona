"""
app/repositories/in_memory/site_repository.py

In-memory implementation of SiteRepository (Protocol, Decision 9).

Every read and write checks both tenant_id and client_id against the
stored record — a site_id alone is never sufficient.

update() rejects a change to tenant_id or client_id (identity-defining
fields, same reasoning as identity-service's MembershipRepository).
No archived-client guard here — that's Client's own concern, already
checked upstream by SiteService via ClientService before this
repository is ever called (see site_repository.py's Protocol
docstring).
"""

from uuid import UUID

from app.models.address import Address
from app.models.site import Site
from app.repositories.exceptions import ImmutableFieldError, RecordNotFoundError
from app.repositories.in_memory.store import InMemoryStore


class InMemorySiteRepository:
    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        label: str,
        address: Address,
        is_primary: bool = False,
    ) -> Site:
        async with self._store.lock:
            site = Site(
                client_id=client_id,
                tenant_id=tenant_id,
                label=label,
                address=address,
                is_primary=is_primary,
            )
            stored = site.model_copy(deep=True)
            self._store.sites_by_id[site.id] = stored
            self._store.site_ids_by_client.setdefault(client_id, []).append(site.id)
            return stored.model_copy(deep=True)

    async def get_by_id(
        self, *, tenant_id: UUID, client_id: UUID, site_id: UUID
    ) -> Site | None:
        site = self._store.sites_by_id.get(site_id)
        if site is None or site.tenant_id != tenant_id or site.client_id != client_id:
            return None
        return site.model_copy(deep=True)

    async def get_primary(self, *, tenant_id: UUID, client_id: UUID) -> Site | None:
        for site_id in self._store.site_ids_by_client.get(client_id, []):
            site = self._store.sites_by_id[site_id]
            if site.tenant_id == tenant_id and site.is_primary:
                return site.model_copy(deep=True)
        return None

    async def list_by_client(self, *, tenant_id: UUID, client_id: UUID) -> list[Site]:
        return [
            self._store.sites_by_id[i].model_copy(deep=True)
            for i in self._store.site_ids_by_client.get(client_id, [])
            if self._store.sites_by_id[i].tenant_id == tenant_id
        ]

    async def update(self, *, site: Site) -> Site:
        async with self._store.lock:
            existing = self._store.sites_by_id.get(site.id)
            if existing is None:
                raise RecordNotFoundError(entity="site", identifier=site.id)

            if existing.tenant_id != site.tenant_id:
                raise ImmutableFieldError(
                    entity="site",
                    field="tenant_id",
                    identifier=site.id,
                    expected=existing.tenant_id,
                    actual=site.tenant_id,
                )
            if existing.client_id != site.client_id:
                raise ImmutableFieldError(
                    entity="site",
                    field="client_id",
                    identifier=site.id,
                    expected=existing.client_id,
                    actual=site.client_id,
                )

            self._store.sites_by_id[site.id] = site.model_copy(deep=True)
            return site.model_copy(deep=True)

    async def delete(self, *, tenant_id: UUID, client_id: UUID, site_id: UUID) -> None:
        async with self._store.lock:
            existing = self._store.sites_by_id.get(site_id)
            if (
                existing is None
                or existing.tenant_id != tenant_id
                or existing.client_id != client_id
            ):
                raise RecordNotFoundError(entity="site", identifier=site_id)

            del self._store.sites_by_id[site_id]
            ids = self._store.site_ids_by_client.get(client_id)
            if ids is not None and site_id in ids:
                ids.remove(site_id)
