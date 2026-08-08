"""
tests/unit/repositories/test_site_repository.py

Contract tests for InMemorySiteRepository — client-service-
architecture.md Decision 4.
"""

from uuid import uuid4

import pytest

from app.models.address import Address
from app.repositories.exceptions import ImmutableFieldError, RecordNotFoundError
from app.repositories.in_memory import InMemorySiteRepository


def _address() -> Address:
    return Address(line1="14 Colmore Row", city="Birmingham", postcode="B3 2QD")


class TestCreate:
    async def test_create_returns_independent_copy(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="A", address=_address()
        )
        site.label = "Mutated"
        refetched = await site_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, site_id=site.id
        )
        assert refetched is not None
        assert refetched.label == "A"


class TestGetById:
    async def test_wrong_client_id_returns_none(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="A", address=_address()
        )
        assert (
            await site_repo.get_by_id(
                tenant_id=tenant_id, client_id=uuid4(), site_id=site.id
            )
            is None
        )

    async def test_wrong_tenant_returns_none(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="A", address=_address()
        )
        assert (
            await site_repo.get_by_id(
                tenant_id=uuid4(), client_id=client_id, site_id=site.id
            )
            is None
        )


class TestGetPrimary:
    async def test_returns_none_when_no_primary(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        await site_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            label="A",
            address=_address(),
            is_primary=False,
        )
        assert (
            await site_repo.get_primary(tenant_id=tenant_id, client_id=client_id)
            is None
        )

    async def test_returns_the_primary_site(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        await site_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            label="Not primary",
            address=_address(),
        )
        primary = await site_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            label="Primary",
            address=_address(),
            is_primary=True,
        )
        found = await site_repo.get_primary(tenant_id=tenant_id, client_id=client_id)
        assert found is not None
        assert found.id == primary.id

    async def test_scoped_to_client(self, site_repo: InMemorySiteRepository) -> None:
        """A primary site under one client must never leak into
        another client's get_primary() call, even within the same
        tenant."""
        tenant_id = uuid4()
        client_a, client_b = uuid4(), uuid4()
        await site_repo.create(
            tenant_id=tenant_id,
            client_id=client_a,
            label="A",
            address=_address(),
            is_primary=True,
        )
        assert (
            await site_repo.get_primary(tenant_id=tenant_id, client_id=client_b) is None
        )


class TestListByClient:
    async def test_only_returns_matching_client(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id = uuid4()
        client_a, client_b = uuid4(), uuid4()
        await site_repo.create(
            tenant_id=tenant_id, client_id=client_a, label="A", address=_address()
        )
        await site_repo.create(
            tenant_id=tenant_id, client_id=client_b, label="B", address=_address()
        )

        sites = await site_repo.list_by_client(tenant_id=tenant_id, client_id=client_a)
        assert len(sites) == 1
        assert sites[0].label == "A"


class TestUpdate:
    async def test_update_persists_changes(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="Old", address=_address()
        )
        site.label = "New"
        updated = await site_repo.update(site=site)
        assert updated.label == "New"

    async def test_update_missing_record_raises(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="A", address=_address()
        )
        site.id = uuid4()
        with pytest.raises(RecordNotFoundError):
            await site_repo.update(site=site)

    async def test_update_changing_tenant_id_raises(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="A", address=_address()
        )
        tampered_tenant_id = uuid4()
        site.tenant_id = tampered_tenant_id
        with pytest.raises(ImmutableFieldError) as exc_info:
            await site_repo.update(site=site)
        assert exc_info.value.entity == "site"
        assert exc_info.value.field == "tenant_id"
        assert exc_info.value.expected == tenant_id
        assert exc_info.value.actual == tampered_tenant_id

    async def test_update_changing_client_id_raises(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="A", address=_address()
        )
        tampered_client_id = uuid4()
        site.client_id = tampered_client_id
        with pytest.raises(ImmutableFieldError) as exc_info:
            await site_repo.update(site=site)
        assert exc_info.value.entity == "site"
        assert exc_info.value.field == "client_id"
        assert exc_info.value.expected == client_id
        assert exc_info.value.actual == tampered_client_id


class TestDelete:
    async def test_delete_removes_record(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        site = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="A", address=_address()
        )
        await site_repo.delete(
            tenant_id=tenant_id, client_id=client_id, site_id=site.id
        )
        assert (
            await site_repo.get_by_id(
                tenant_id=tenant_id, client_id=client_id, site_id=site.id
            )
            is None
        )

    async def test_delete_missing_record_raises(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        with pytest.raises(RecordNotFoundError):
            await site_repo.delete(
                tenant_id=uuid4(), client_id=uuid4(), site_id=uuid4()
            )

    async def test_delete_does_not_affect_other_sites_for_same_client(
        self, site_repo: InMemorySiteRepository
    ) -> None:
        """Guards the index-cleanup logic specifically — deleting one
        site must only remove its own id from site_ids_by_client, not
        clobber the whole list."""
        tenant_id, client_id = uuid4(), uuid4()
        keep = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="Keep", address=_address()
        )
        remove = await site_repo.create(
            tenant_id=tenant_id, client_id=client_id, label="Remove", address=_address()
        )
        await site_repo.delete(
            tenant_id=tenant_id, client_id=client_id, site_id=remove.id
        )

        remaining = await site_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id
        )
        assert [s.id for s in remaining] == [keep.id]
