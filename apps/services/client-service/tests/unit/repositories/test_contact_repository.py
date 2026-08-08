"""
tests/unit/repositories/test_contact_repository.py

Contract tests for InMemoryContactRepository — client-service-
architecture.md Decisions 4, 9.
"""

from uuid import uuid4

import pytest

from app.repositories.exceptions import ImmutableFieldError, RecordNotFoundError
from app.repositories.in_memory import InMemoryContactRepository


class TestCreate:
    async def test_create_client_level_contact(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        contact = await contact_repo.create(
            tenant_id=uuid4(),
            client_id=uuid4(),
            name="Priya Shah",
            phone="+44 121 000 0000",
        )
        assert contact.site_id is None


class TestGetPrimary:
    async def test_scoped_to_client(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        tenant_id = uuid4()
        client_a, client_b = uuid4(), uuid4()
        await contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_a,
            name="A",
            phone="+44 121 000 0000",
            is_primary=True,
        )
        assert (
            await contact_repo.get_primary(tenant_id=tenant_id, client_id=client_b)
            is None
        )


class TestListByClient:
    async def test_site_id_filter(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        tenant_id, client_id, site_id = uuid4(), uuid4(), uuid4()
        await contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            site_id=site_id,
            name="Site Contact",
            phone="+44 121 000 0000",
        )
        await contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            name="Client-level Contact",
            email="a@b.com",
        )

        filtered = await contact_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )
        assert len(filtered) == 1
        assert filtered[0].name == "Site Contact"

    async def test_site_id_filter_matching_nothing_returns_empty_list(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        """01-api-contract.md: a site_id that matches nothing returns
        200 [], not an error. This is the repository behavior that
        makes that contract true — normal empty-list return, no special
        casing needed at the service/route layer."""
        tenant_id, client_id = uuid4(), uuid4()
        await contact_repo.create(
            tenant_id=tenant_id, client_id=client_id, name="A", phone="+44 121 000 0000"
        )
        result = await contact_repo.list_by_client(
            tenant_id=tenant_id, client_id=client_id, site_id=uuid4()
        )
        assert result == []


class TestUpdate:
    async def test_update_changing_tenant_id_raises(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        original_tenant_id = uuid4()
        contact = await contact_repo.create(
            tenant_id=original_tenant_id,
            client_id=uuid4(),
            name="A",
            phone="+44 121 000 0000",
        )
        tampered_tenant_id = uuid4()
        contact.tenant_id = tampered_tenant_id
        with pytest.raises(ImmutableFieldError) as exc_info:
            await contact_repo.update(contact=contact)
        assert exc_info.value.entity == "contact"
        assert exc_info.value.field == "tenant_id"
        assert exc_info.value.expected == original_tenant_id
        assert exc_info.value.actual == tampered_tenant_id

    async def test_update_changing_client_id_raises(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        original_client_id = uuid4()
        contact = await contact_repo.create(
            tenant_id=uuid4(),
            client_id=original_client_id,
            name="A",
            phone="+44 121 000 0000",
        )
        tampered_client_id = uuid4()
        contact.client_id = tampered_client_id
        with pytest.raises(ImmutableFieldError) as exc_info:
            await contact_repo.update(contact=contact)
        assert exc_info.value.entity == "contact"
        assert exc_info.value.field == "client_id"
        assert exc_info.value.expected == original_client_id
        assert exc_info.value.actual == tampered_client_id


class TestClearSiteAssignment:
    """Decision 9 — the single most important behavior in this file."""

    async def test_clears_matching_contacts_only(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        tenant_id, client_id, site_id = uuid4(), uuid4(), uuid4()
        other_site_id = uuid4()

        matching_1 = await contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            site_id=site_id,
            name="A",
            phone="+44 121 000 0001",
        )
        matching_2 = await contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            site_id=site_id,
            name="B",
            phone="+44 121 000 0002",
        )
        unrelated = await contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            site_id=other_site_id,
            name="C",
            phone="+44 121 000 0003",
        )
        client_level = await contact_repo.create(
            tenant_id=tenant_id, client_id=client_id, name="D", phone="+44 121 000 0004"
        )

        count = await contact_repo.clear_site_assignment(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )
        assert count == 2

        refetched_1 = await contact_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, contact_id=matching_1.id
        )
        refetched_2 = await contact_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, contact_id=matching_2.id
        )
        refetched_unrelated = await contact_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, contact_id=unrelated.id
        )
        refetched_client_level = await contact_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, contact_id=client_level.id
        )

        assert refetched_1 is not None and refetched_1.site_id is None
        assert refetched_2 is not None and refetched_2.site_id is None
        assert (
            refetched_unrelated is not None
            and refetched_unrelated.site_id == other_site_id
        )
        assert (
            refetched_client_level is not None
            and refetched_client_level.site_id is None
        )

    async def test_returns_zero_when_nothing_matches(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        tenant_id, client_id = uuid4(), uuid4()
        await contact_repo.create(
            tenant_id=tenant_id, client_id=client_id, name="A", phone="+44 121 000 0000"
        )
        count = await contact_repo.clear_site_assignment(
            tenant_id=tenant_id, client_id=client_id, site_id=uuid4()
        )
        assert count == 0

    async def test_does_not_corrupt_email_or_phone_invariant(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        """clear_site_assignment only touches site_id — this confirms
        it doesn't accidentally trip Contact's email-or-phone
        model_validator via the model_dump()+constructor reconstruction
        path (a real risk if the reconstruction ever picked up stale or
        missing data for unrelated fields)."""
        tenant_id, client_id, site_id = uuid4(), uuid4(), uuid4()
        contact = await contact_repo.create(
            tenant_id=tenant_id,
            client_id=client_id,
            site_id=site_id,
            name="A",
            phone="+44 121 000 0000",
        )
        await contact_repo.clear_site_assignment(
            tenant_id=tenant_id, client_id=client_id, site_id=site_id
        )
        refetched = await contact_repo.get_by_id(
            tenant_id=tenant_id, client_id=client_id, contact_id=contact.id
        )
        assert refetched is not None
        assert refetched.phone == "+44 121 000 0000"

    async def test_scoped_to_tenant(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        """A site_id collision across tenants must never cause
        clear_site_assignment to touch another tenant's contacts."""
        tenant_a, tenant_b = uuid4(), uuid4()
        client_id, site_id = uuid4(), uuid4()

        contact_b = await contact_repo.create(
            tenant_id=tenant_b,
            client_id=client_id,
            site_id=site_id,
            name="B",
            phone="+44 121 000 0000",
        )

        count = await contact_repo.clear_site_assignment(
            tenant_id=tenant_a, client_id=client_id, site_id=site_id
        )
        assert count == 0

        refetched = await contact_repo.get_by_id(
            tenant_id=tenant_b, client_id=client_id, contact_id=contact_b.id
        )
        assert refetched is not None
        assert refetched.site_id == site_id


class TestDelete:
    async def test_delete_missing_record_raises(
        self, contact_repo: InMemoryContactRepository
    ) -> None:
        with pytest.raises(RecordNotFoundError):
            await contact_repo.delete(
                tenant_id=uuid4(), client_id=uuid4(), contact_id=uuid4()
            )
