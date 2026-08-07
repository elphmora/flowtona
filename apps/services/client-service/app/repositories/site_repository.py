"""
app/repositories/site_repository.py

Protocol contract for Site persistence (Decision 9 / Platform
Conventions §4). Every method takes both tenant_id and client_id, never
client_id alone, so a site can never be looked up or written outside
its own tenant's scope.

No archived-state guard exists here — that's Client's own concern.
SiteService confirms client writability via ClientService before
calling into this repository at all (02-sequence-diagrams.md).

get_primary() is a plain lookup primitive, not a business-behaviour
method — is_primary demotion/promotion orchestration (load current
primary, demote, promote, save) lives in SiteService, composed from
this and update(). Keeps the repository/service boundary where the
rest of this project already draws it: repository = persistence,
service = business behaviour.
"""

from typing import Protocol
from uuid import UUID

from app.models.address import Address
from app.models.site import Site


class SiteRepository(Protocol):
    async def create(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        label: str,
        address: Address,
        is_primary: bool = False,
    ) -> Site:
        """Create a new site. is_primary is passed through as already
        resolved by SiteService — this repository doesn't decide
        auto-primary itself, only persists what it's told."""
        ...

    async def get_by_id(
        self, *, tenant_id: UUID, client_id: UUID, site_id: UUID
    ) -> Site | None: ...

    async def get_primary(self, *, tenant_id: UUID, client_id: UUID) -> Site | None:
        """The site currently holding is_primary=True for this client,
        if any (Invariant 2: at most one). A lookup primitive for
        SiteService to compose into the demote/promote workflow."""
        ...

    async def list_by_client(self, *, tenant_id: UUID, client_id: UUID) -> list[Site]:
        """All sites for one client. Not paginated — see
        01-api-contract.md."""
        ...

    async def update(self, *, site: Site) -> Site:
        """Persist changes to an existing site — any field, including
        is_primary."""
        ...

    async def delete(self, *, tenant_id: UUID, client_id: UUID, site_id: UUID) -> None:
        """Hard delete. Does not touch Contact records pointing at this
        site — see ContactRepository.clear_site_assignment() and
        Decision 9's ordering."""
        ...
