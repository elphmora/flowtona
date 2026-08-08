"""
tests/unit/services/test_client_service.py

Service-layer tests for ClientService — orchestration and exception
translation, not repository behavior (that's
tests/unit/repositories/test_client_repository.py's job).
"""

from uuid import uuid4

import pytest

from app.exceptions.client import (
    ArchiveViaUpdateNotAllowedError,
    ClientArchivedError,
    ClientNotFoundError,
)
from app.models.enums import ClientStatus, ClientType
from app.services.client_service import ClientService


class TestCreateClient:
    async def test_creates_active_client(self, client_service: ClientService) -> None:
        client = await client_service.create_client(
            tenant_id=uuid4(),
            name="Birmingham Plumbing Co.",
            client_type=ClientType.COMMERCIAL,
        )
        assert client.status == ClientStatus.ACTIVE
        assert client.name == "Birmingham Plumbing Co."
        assert client.client_type == ClientType.COMMERCIAL


class TestGetClient:
    async def test_returns_existing_client(self, client_service: ClientService) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        found = await client_service.get_client(
            tenant_id=created.tenant_id, client_id=created.id
        )
        assert found.id == created.id

    async def test_missing_client_raises_client_not_found(
        self, client_service: ClientService
    ) -> None:
        with pytest.raises(ClientNotFoundError):
            await client_service.get_client(tenant_id=uuid4(), client_id=uuid4())


class TestUpdateClient:
    async def test_updates_name(self, client_service: ClientService) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="Old", client_type=ClientType.RESIDENTIAL
        )
        updated = await client_service.update_client(
            tenant_id=created.tenant_id, client_id=created.id, name="New"
        )
        assert updated.name == "New"

    async def test_setting_status_archived_raises(
        self, client_service: ClientService
    ) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        with pytest.raises(ArchiveViaUpdateNotAllowedError):
            await client_service.update_client(
                tenant_id=created.tenant_id,
                client_id=created.id,
                status=ClientStatus.ARCHIVED,
            )

    async def test_setting_status_active_inactive_still_works(
        self, client_service: ClientService
    ) -> None:
        """Confirms the archive-via-update guard is specific to
        ARCHIVED, not a blanket rejection of the status parameter."""
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        updated = await client_service.update_client(
            tenant_id=created.tenant_id,
            client_id=created.id,
            status=ClientStatus.INACTIVE,
        )
        assert updated.status == ClientStatus.INACTIVE

    async def test_missing_client_raises_not_found_even_with_archive_attempt(
        self, client_service: ClientService
    ) -> None:
        """The precedence fix from review: existence is checked BEFORE
        the archive-via-update rule. A nonexistent client requesting
        status=ARCHIVED must surface ClientNotFoundError, not
        ArchiveViaUpdateNotAllowedError — "does this exist" outranks
        "is this operation allowed on it." """
        with pytest.raises(ClientNotFoundError):
            await client_service.update_client(
                tenant_id=uuid4(), client_id=uuid4(), status=ClientStatus.ARCHIVED
            )

    async def test_missing_client_raises_client_not_found(
        self, client_service: ClientService
    ) -> None:
        with pytest.raises(ClientNotFoundError):
            await client_service.update_client(
                tenant_id=uuid4(), client_id=uuid4(), name="X"
            )

    async def test_update_against_archived_client_raises_client_archived(
        self, client_service: ClientService
    ) -> None:
        """Confirms repository RecordArchivedError is correctly
        translated into ClientService's own ClientArchivedError."""
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        await client_service.archive_client(
            tenant_id=created.tenant_id, client_id=created.id
        )

        with pytest.raises(ClientArchivedError):
            await client_service.update_client(
                tenant_id=created.tenant_id,
                client_id=created.id,
                name="Attempted Rename",
            )


class TestArchiveClient:
    async def test_archives_client(self, client_service: ClientService) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        archived = await client_service.archive_client(
            tenant_id=created.tenant_id, client_id=created.id
        )
        assert archived.status == ClientStatus.ARCHIVED

    async def test_is_idempotent(self, client_service: ClientService) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        first = await client_service.archive_client(
            tenant_id=created.tenant_id, client_id=created.id
        )
        second = await client_service.archive_client(
            tenant_id=created.tenant_id, client_id=created.id
        )
        assert first.id == second.id
        assert first.status == second.status == ClientStatus.ARCHIVED
        # Idempotent archive() returns the stored record unchanged on
        # the second call (InMemoryClientRepository.archive() is a
        # no-op when already archived) — updated_at must NOT advance
        # a second time, since nothing actually changed.
        assert second.updated_at == first.updated_at

    async def test_missing_client_raises_client_not_found(
        self, client_service: ClientService
    ) -> None:
        with pytest.raises(ClientNotFoundError):
            await client_service.archive_client(tenant_id=uuid4(), client_id=uuid4())


class TestRequireWritableClient:
    async def test_returns_client_when_active(
        self, client_service: ClientService
    ) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        result = await client_service.require_writable_client(
            tenant_id=created.tenant_id, client_id=created.id
        )
        assert result.id == created.id

    async def test_raises_client_archived_when_archived(
        self, client_service: ClientService
    ) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        await client_service.archive_client(
            tenant_id=created.tenant_id, client_id=created.id
        )

        with pytest.raises(ClientArchivedError):
            await client_service.require_writable_client(
                tenant_id=created.tenant_id, client_id=created.id
            )

    async def test_raises_client_not_found_when_missing(
        self, client_service: ClientService
    ) -> None:
        with pytest.raises(ClientNotFoundError):
            await client_service.require_writable_client(
                tenant_id=uuid4(), client_id=uuid4()
            )


class TestArchivedClientRemainsReadable:
    """Decision 5: archived means immutable, not invisible. Writes are
    blocked (covered above); reads must keep working unchanged."""

    async def test_get_client_still_works_after_archive(
        self, client_service: ClientService
    ) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        await client_service.archive_client(
            tenant_id=created.tenant_id, client_id=created.id
        )

        found = await client_service.get_client(
            tenant_id=created.tenant_id, client_id=created.id
        )
        assert found.status == ClientStatus.ARCHIVED

    async def test_list_clients_still_includes_archived_by_default(
        self, client_service: ClientService
    ) -> None:
        created = await client_service.create_client(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        await client_service.archive_client(
            tenant_id=created.tenant_id, client_id=created.id
        )

        page = await client_service.list_clients(tenant_id=created.tenant_id)
        assert page.total == 1
        assert page.items[0].id == created.id
