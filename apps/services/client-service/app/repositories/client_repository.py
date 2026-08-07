"""
app/repositories/client_repository.py

Protocol contract for Client persistence (Decision 9 / Platform
Conventions §4). Every method takes tenant_id explicitly (Platform
Conventions §5).

archive() and update() are separate methods, not one generic
status-setting update() — see Decision 5 for the full reasoning
(archived is a one-way, fully-immutable terminal state; archive() is
idempotent, update() rejects any write once archived).

list_by_tenant() returns a ClientPage (items + total) rather than a
bare list, so both are computed against the same filtered query — not
two calls that could observe different snapshots under concurrent
writes.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.models.client import Client
from app.models.enums import ClientStatus, ClientType


@dataclass
class ClientPage:
    """Return shape for list_by_tenant() — items plus the total count
    for the same filtered query."""

    items: list[Client]
    total: int


class ClientRepository(Protocol):
    async def create(
        self,
        *,
        tenant_id: UUID,
        name: str,
        client_type: ClientType,
    ) -> Client:
        """Create a new client. status is repository-owned, always
        ACTIVE on creation — callers never set it here (Decision 5)."""
        ...

    async def get_by_id(self, *, tenant_id: UUID, client_id: UUID) -> Client | None: ...

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
        """Filtered, paginated list — GET /v1/clients. name is a
        substring match; status/client_type are exact matches.
        limit/offset are already validated/clamped by the API schema
        layer before reaching this method (Decision 7)."""
        ...

    async def update(self, *, client: Client) -> Client:
        """Persist changes to an existing client. Raises
        RecordArchivedError if the stored record is currently ARCHIVED
        (Decision 5). Raises RecordNotFoundError if the record no
        longer exists at write time."""
        ...

    async def archive(
        self, *, tenant_id: UUID, client_id: UUID, archived_at: datetime
    ) -> Client:
        """Atomically transition a client to ARCHIVED. Idempotent — a
        no-op if already ARCHIVED. Raises RecordNotFoundError if the
        client doesn't exist."""
        ...
