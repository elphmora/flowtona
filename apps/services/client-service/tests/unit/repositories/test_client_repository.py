"""
tests/unit/repositories/test_client_repository.py

Contract tests for InMemoryClientRepository against ClientRepository's
Protocol — client-service-architecture.md Decisions 4, 5, 9.
"""

from uuid import uuid4

import pytest

from app.models.enums import ClientStatus, ClientType
from app.repositories.exceptions import (
    ImmutableFieldError,
    RecordArchivedError,
    RecordNotFoundError,
)
from app.repositories.in_memory import InMemoryClientRepository


class TestCreate:
    async def test_create_defaults_to_active(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        client = await client_repo.create(
            tenant_id=uuid4(),
            name="Birmingham Plumbing Co.",
            client_type=ClientType.COMMERCIAL,
        )
        assert client.status == ClientStatus.ACTIVE
        assert client.id is not None

    async def test_create_returns_independent_copy(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        """Mutating the returned object must never affect stored state —
        this is what model_copy(deep=True) on every read/write exists
        to guarantee."""
        client = await client_repo.create(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        client.name = "Mutated"
        refetched = await client_repo.get_by_id(
            tenant_id=client.tenant_id, client_id=client.id
        )
        assert refetched is not None
        assert refetched.name == "A"


class TestGetById:
    async def test_get_by_id_found(self, client_repo: InMemoryClientRepository) -> None:
        created = await client_repo.create(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        found = await client_repo.get_by_id(
            tenant_id=created.tenant_id, client_id=created.id
        )
        assert found == created

    async def test_get_by_id_missing_returns_none(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        assert await client_repo.get_by_id(tenant_id=uuid4(), client_id=uuid4()) is None

    async def test_get_by_id_wrong_tenant_returns_none(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        """Cross-tenant isolation is the whole point of client-service's
        Decision 2 — this is the single most important repository test
        in this file."""
        created = await client_repo.create(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        other_tenant = uuid4()
        assert (
            await client_repo.get_by_id(tenant_id=other_tenant, client_id=created.id)
            is None
        )


class TestListByTenant:
    async def test_only_returns_matching_tenant(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        tenant_a, tenant_b = uuid4(), uuid4()
        await client_repo.create(
            tenant_id=tenant_a, name="A", client_type=ClientType.RESIDENTIAL
        )
        await client_repo.create(
            tenant_id=tenant_b, name="B", client_type=ClientType.RESIDENTIAL
        )

        page = await client_repo.list_by_tenant(tenant_id=tenant_a)
        assert page.total == 1
        assert page.items[0].name == "A"

    async def test_name_filter_is_substring_case_insensitive(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        tenant_id = uuid4()
        await client_repo.create(
            tenant_id=tenant_id,
            name="Birmingham Plumbing Co.",
            client_type=ClientType.COMMERCIAL,
        )
        await client_repo.create(
            tenant_id=tenant_id,
            name="London Electrical",
            client_type=ClientType.COMMERCIAL,
        )

        page = await client_repo.list_by_tenant(tenant_id=tenant_id, name="birmingham")
        assert page.total == 1
        assert page.items[0].name == "Birmingham Plumbing Co."

    async def test_status_and_client_type_filters(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        tenant_id = uuid4()
        residential = await client_repo.create(
            tenant_id=tenant_id, name="A", client_type=ClientType.RESIDENTIAL
        )
        await client_repo.create(
            tenant_id=tenant_id, name="B", client_type=ClientType.COMMERCIAL
        )
        await client_repo.archive(
            tenant_id=tenant_id,
            client_id=residential.id,
            archived_at=residential.updated_at,
        )

        commercial_only = await client_repo.list_by_tenant(
            tenant_id=tenant_id, client_type=ClientType.COMMERCIAL
        )
        assert commercial_only.total == 1

        archived_only = await client_repo.list_by_tenant(
            tenant_id=tenant_id, status=ClientStatus.ARCHIVED
        )
        assert archived_only.total == 1
        assert archived_only.items[0].id == residential.id

    async def test_pagination_total_reflects_filtered_count_not_page_size(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        """The bug this guards against: total should be the count of
        ALL matching records, not just how many fit on this page —
        conflating the two would break every client beyond page one."""
        tenant_id = uuid4()
        for i in range(5):
            await client_repo.create(
                tenant_id=tenant_id,
                name=f"Client {i}",
                client_type=ClientType.RESIDENTIAL,
            )

        page = await client_repo.list_by_tenant(tenant_id=tenant_id, limit=2, offset=0)
        assert page.total == 5
        assert len(page.items) == 2

    async def test_offset_moves_the_window(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        tenant_id = uuid4()
        created = [
            await client_repo.create(
                tenant_id=tenant_id,
                name=f"Client {i}",
                client_type=ClientType.RESIDENTIAL,
            )
            for i in range(3)
        ]

        page = await client_repo.list_by_tenant(tenant_id=tenant_id, limit=1, offset=1)
        assert page.items[0].id == created[1].id


class TestUpdate:
    async def test_update_persists_changes(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        created = await client_repo.create(
            tenant_id=uuid4(), name="Old Name", client_type=ClientType.RESIDENTIAL
        )
        created.name = "New Name"
        updated = await client_repo.update(client=created)
        assert updated.name == "New Name"

        refetched = await client_repo.get_by_id(
            tenant_id=created.tenant_id, client_id=created.id
        )
        assert refetched is not None
        assert refetched.name == "New Name"

    async def test_update_missing_record_raises(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        tenant_id = uuid4()
        created = await client_repo.create(
            tenant_id=tenant_id, name="A", client_type=ClientType.RESIDENTIAL
        )
        created.id = uuid4()  # simulate a record that was never actually stored
        with pytest.raises(RecordNotFoundError):
            await client_repo.update(client=created)

    async def test_update_changing_tenant_id_raises(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        created = await client_repo.create(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        original_tenant_id = created.tenant_id
        tampered_tenant_id = uuid4()
        created.tenant_id = tampered_tenant_id
        with pytest.raises(ImmutableFieldError) as exc_info:
            await client_repo.update(client=created)
        assert exc_info.value.entity == "client"
        assert exc_info.value.field == "tenant_id"
        assert exc_info.value.expected == original_tenant_id
        assert exc_info.value.actual == tampered_tenant_id

    async def test_update_against_archived_client_raises(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        created = await client_repo.create(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        archived = await client_repo.archive(
            tenant_id=created.tenant_id,
            client_id=created.id,
            archived_at=created.updated_at,
        )
        archived.name = "Attempted Rename"
        with pytest.raises(RecordArchivedError):
            await client_repo.update(client=archived)


class TestArchive:
    async def test_archive_transitions_status(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        created = await client_repo.create(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        archived = await client_repo.archive(
            tenant_id=created.tenant_id,
            client_id=created.id,
            archived_at=created.updated_at,
        )
        assert archived.status == ClientStatus.ARCHIVED

    async def test_archive_is_idempotent(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        """01-api-contract.md: archiving an already-archived client
        returns 204 again, not an error. This is the repository-level
        behavior that makes that possible."""
        created = await client_repo.create(
            tenant_id=uuid4(), name="A", client_type=ClientType.RESIDENTIAL
        )
        first = await client_repo.archive(
            tenant_id=created.tenant_id,
            client_id=created.id,
            archived_at=created.updated_at,
        )
        second = await client_repo.archive(
            tenant_id=created.tenant_id,
            client_id=created.id,
            archived_at=created.updated_at,
        )
        assert first.status == second.status == ClientStatus.ARCHIVED

    async def test_archive_missing_record_raises(
        self, client_repo: InMemoryClientRepository
    ) -> None:
        from app.models.types import utc_now

        with pytest.raises(RecordNotFoundError):
            await client_repo.archive(
                tenant_id=uuid4(), client_id=uuid4(), archived_at=utc_now()
            )
