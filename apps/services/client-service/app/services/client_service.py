"""
app/services/client_service.py

Entity service for Client — thin wrapper over ClientRepository,
translating repository-level exceptions into ClientService's own
domain exceptions per 01-api-contract.md's error catalog.

require_writable_client() is the primitive SiteService/ContactService
call before any write of their own (02-sequence-diagrams.md) — the
single place "is this client archived?" gets checked, so
SiteRepository/ContactRepository don't need to know about
Client.status at all (see those Protocols' own docstrings on why that
check deliberately isn't there).

update_client() rejects status=ARCHIVED outright, requiring
archive_client() for that transition instead — enforced here, in the
service layer, not deferred to a future API schema. A schema-only
guard would only stop HTTP callers; anything calling ClientService
directly (a CLI, a migration script, a background job) would bypass
it entirely. The business rule belongs at the domain boundary, not
only at the edge that happens to receive HTTP requests today.

Not implemented yet, expected to appear naturally later:
require_client() — a read-only counterpart to require_writable_client()
for operations that need a client to exist but don't care whether it's
archived. No current caller needs it.
"""

from uuid import UUID

from app.exceptions.client import (
    ArchiveViaUpdateNotAllowedError,
    ClientArchivedError,
    ClientNotFoundError,
)
from app.metrics.business_metrics import (
    CLIENT_ARCHIVED_TOTAL,
    CLIENT_ARCHIVED_WRITE_REJECTED_TOTAL,
    CLIENT_CREATED_TOTAL,
)
from app.models.client import Client
from app.models.enums import ClientStatus, ClientType
from app.models.types import utc_now
from app.repositories.client_repository import ClientPage, ClientRepository
from app.repositories.exceptions import RecordArchivedError, RecordNotFoundError


class ClientService:
    def __init__(self, client_repo: ClientRepository) -> None:
        self._client_repo = client_repo

    async def create_client(
        self, *, tenant_id: UUID, name: str, client_type: ClientType
    ) -> Client:
        client = await self._client_repo.create(
            tenant_id=tenant_id, name=name, client_type=client_type
        )
        CLIENT_CREATED_TOTAL.inc()
        return client

    async def get_client(self, *, tenant_id: UUID, client_id: UUID) -> Client:
        client = await self._client_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id
        )
        if client is None:
            raise ClientNotFoundError()
        return client

    async def list_clients(
        self,
        *,
        tenant_id: UUID,
        name: str | None = None,
        status: ClientStatus | None = None,
        client_type: ClientType | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ClientPage:
        return await self._client_repo.list_by_tenant(
            tenant_id=tenant_id,
            name=name,
            status=status,
            client_type=client_type,
            limit=limit,
            offset=offset,
        )

    async def update_client(
        self,
        *,
        tenant_id: UUID,
        client_id: UUID,
        name: str | None = None,
        client_type: ClientType | None = None,
        status: ClientStatus | None = None,
    ) -> Client:
        """PATCH. status is restricted to ACTIVE<->INACTIVE — see
        module docstring for why ARCHIVED is rejected here rather than
        only at a future schema layer. Existence is checked before the
        archive-via-update rule, not after — a nonexistent client
        should surface ClientNotFoundError, not
        ArchiveViaUpdateNotAllowedError, even if the caller also
        requested an invalid transition. Whether a resource exists
        outranks whether an operation is allowed on it."""
        existing = await self.get_client(tenant_id=tenant_id, client_id=client_id)

        if status == ClientStatus.ARCHIVED:
            raise ArchiveViaUpdateNotAllowedError()

        updated = existing.model_copy()
        if name is not None:
            updated.name = name
        if client_type is not None:
            updated.client_type = client_type
        if status is not None:
            updated.status = status
        updated.updated_at = utc_now()

        try:
            return await self._client_repo.update(client=updated)
        except RecordArchivedError as exc:
            # A second, independent path to ClientArchivedError,
            # distinct from require_writable_client() below — update()
            # catches the repository's own archived-check directly,
            # rather than calling require_writable_client() first.
            # Counted here too, or a PATCH against an archived client
            # (the most likely real case a caller hits) would silently
            # not increment this counter at all.
            CLIENT_ARCHIVED_WRITE_REJECTED_TOTAL.inc()
            raise ClientArchivedError() from exc
        except RecordNotFoundError as exc:
            raise ClientNotFoundError() from exc

    async def archive_client(self, *, tenant_id: UUID, client_id: UUID) -> Client:
        """Idempotent (ClientRepository.archive()'s own contract) —
        the metric must not be. A retried DELETE against an already-
        archived client is one real archive event, not two; checking
        status first, before calling archive(), is what makes the
        counter reflect actual transitions rather than API calls."""
        existing = await self.get_client(tenant_id=tenant_id, client_id=client_id)
        was_already_archived = existing.status == ClientStatus.ARCHIVED

        try:
            client = await self._client_repo.archive(
                tenant_id=tenant_id, client_id=client_id, archived_at=utc_now()
            )
        except RecordNotFoundError as exc:
            raise ClientNotFoundError() from exc

        if not was_already_archived:
            CLIENT_ARCHIVED_TOTAL.inc()
        return client

    async def require_writable_client(
        self, *, tenant_id: UUID, client_id: UUID
    ) -> Client:
        """SiteService/ContactService call this before any write of
        their own. Raises ClientNotFoundError or ClientArchivedError;
        returns the client otherwise."""
        client = await self.get_client(tenant_id=tenant_id, client_id=client_id)
        if client.status == ClientStatus.ARCHIVED:
            CLIENT_ARCHIVED_WRITE_REJECTED_TOTAL.inc()
            raise ClientArchivedError()
        return client
