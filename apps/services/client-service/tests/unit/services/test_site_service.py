"""
tests/unit/services/test_site_service.py

Service-layer tests for SiteService — is_primary orchestration and
Decision 9's delete_site() sequence.
"""

import asyncio
from uuid import uuid4

import pytest

from app.exceptions.client import ClientArchivedError, ClientNotFoundError
from app.exceptions.site import SiteNotFoundError
from app.models.address import Address
from app.models.enums import ClientType
from app.services.client_service import ClientService
from app.services.contact_service import ContactService
from app.services.site_service import SiteService


def _address() -> Address:
    return Address(line1="14 Colmore Row", city="Birmingham", postcode="B3 2QD")


async def _make_client(client_service: ClientService):
    return await client_service.create_client(
        tenant_id=uuid4(), name="Test Co.", client_type=ClientType.COMMERCIAL
    )


class TestCreateSite:
    async def test_first_site_is_auto_primary(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="HQ",
            address=_address(),
        )
        assert site.is_primary is True

    async def test_second_site_not_primary_by_default(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="First",
            address=_address(),
        )
        second = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="Second",
            address=_address(),
        )
        assert second.is_primary is False

    async def test_explicit_primary_on_second_site_demotes_first(
        self,
        client_service: ClientService,
        site_service: SiteService,
    ) -> None:
        """The critical no-two-primaries proof — this is exactly the
        bug caught and fixed during design (demote-before-promote)."""
        client = await _make_client(client_service)
        first = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="First",
            address=_address(),
        )
        assert first.is_primary is True

        second = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="Second",
            address=_address(),
            is_primary=True,
        )
        assert second.is_primary is True

        all_sites = await site_service.list_sites(
            tenant_id=client.tenant_id, client_id=client.id
        )
        primary_sites = [s for s in all_sites if s.is_primary]
        assert len(primary_sites) == 1
        assert primary_sites[0].id == second.id

    async def test_requires_writable_client_raises_when_archived(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        with pytest.raises(ClientArchivedError):
            await site_service.create_site(
                tenant_id=client.tenant_id,
                client_id=client.id,
                label="A",
                address=_address(),
            )

    async def test_requires_writable_client_raises_when_client_missing(
        self, site_service: SiteService
    ) -> None:
        with pytest.raises(ClientNotFoundError):
            await site_service.create_site(
                tenant_id=uuid4(), client_id=uuid4(), label="A", address=_address()
            )


class TestGetSite:
    async def test_missing_site_raises_site_not_found(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        with pytest.raises(SiteNotFoundError):
            await site_service.get_site(
                tenant_id=client.tenant_id, client_id=client.id, site_id=uuid4()
            )


class TestUpdateSite:
    async def test_setting_primary_true_demotes_current_primary(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        first = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="First",
            address=_address(),
        )
        second = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="Second",
            address=_address(),
        )
        assert first.is_primary is True
        assert second.is_primary is False

        await site_service.update_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            site_id=second.id,
            is_primary=True,
        )

        all_sites = await site_service.list_sites(
            tenant_id=client.tenant_id, client_id=client.id
        )
        primary_sites = [s for s in all_sites if s.is_primary]
        assert len(primary_sites) == 1
        assert primary_sites[0].id == second.id

    async def test_requires_writable_client_raises_when_archived(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="A",
            address=_address(),
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        with pytest.raises(ClientArchivedError):
            await site_service.update_site(
                tenant_id=client.tenant_id,
                client_id=client.id,
                site_id=site.id,
                label="Renamed",
            )


class TestDeleteSite:
    async def test_clears_contact_assignments_and_deletes_site(
        self,
        client_service: ClientService,
        site_service: SiteService,
        contact_service: ContactService,
    ) -> None:
        """Decision 9's observable outcome: a happy-path test can't
        literally prove call ORDER without mocks (not this codebase's
        convention — real objects throughout), but it can and does
        prove the POST-CONDITION that ordering exists to guarantee:
        every contact that pointed at the deleted site is detached,
        not left referencing a site that no longer exists."""
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="A",
            address=_address(),
        )
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            site_id=site.id,
            name="Priya",
            phone="+44 121 000 0000",
        )

        affected_count = await site_service.delete_site(
            tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
        )
        assert affected_count == 1

        refetched_contact = await contact_service.get_contact(
            tenant_id=client.tenant_id, client_id=client.id, contact_id=contact.id
        )
        assert refetched_contact.site_id is None

        with pytest.raises(SiteNotFoundError):
            await site_service.get_site(
                tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
            )

    async def test_returns_zero_when_no_contacts_assigned(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="A",
            address=_address(),
        )
        affected_count = await site_service.delete_site(
            tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
        )
        assert affected_count == 0

    async def test_requires_writable_client_raises_when_archived(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="A",
            address=_address(),
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        with pytest.raises(ClientArchivedError):
            await site_service.delete_site(
                tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
            )

    async def test_missing_site_raises_site_not_found(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        with pytest.raises(SiteNotFoundError):
            await site_service.delete_site(
                tenant_id=client.tenant_id, client_id=client.id, site_id=uuid4()
            )

    async def test_concurrent_delete_translates_repository_not_found(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        """Not run/verified in this sandbox (no asyncio runtime here) —
        flagging that explicitly rather than presenting it as confirmed.
        Exercises a genuine production scenario: two simultaneous
        DELETE requests for the same site (double-click, client retry
        after a timed-out first attempt). Whichever call reaches
        SiteRepository.delete() second hits RecordNotFoundError from
        the repository itself, not from SiteService's own get_site()
        pre-check — this is the specific code path the try/except in
        delete_site() exists to translate. Asserts exactly one success
        and one SiteNotFoundError, not which particular call wins;
        asyncio's cooperative scheduling (no forced interleaving
        without a real suspension point) makes the outcome
        deterministic in practice, but the test doesn't depend on
        knowing which of the two calls that is.

        CAUTION if this ever starts flaking under CI: that's a signal
        the repository implementation's timing changed (e.g. real
        I/O added later, a Postgres-backed repository with genuine
        latency), not necessarily that the production translation
        logic broke. The fix in that case is a more deterministic
        synchronization mechanism in the test (e.g. an explicit
        barrier/event controlling exactly when each coroutine proceeds
        past the pre-check), not disabling or deleting this test — the
        translation path itself still needs coverage."""
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="A",
            address=_address(),
        )

        results = await asyncio.gather(
            site_service.delete_site(
                tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
            ),
            site_service.delete_site(
                tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
            ),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], SiteNotFoundError)


class TestArchivedClientRemainsReadable:
    """Decision 5: archived means immutable, not invisible."""

    async def test_get_site_still_works_after_client_archived(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="A",
            address=_address(),
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        found = await site_service.get_site(
            tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
        )
        assert found.id == site.id

    async def test_list_sites_still_works_after_client_archived(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        client = await _make_client(client_service)
        await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="A",
            address=_address(),
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        sites = await site_service.list_sites(
            tenant_id=client.tenant_id, client_id=client.id
        )
        assert len(sites) == 1


class TestCrossClientBoundary:
    """A promote/update attempt scoped to Client A must never reach a
    site actually belonging to Client B, even within the same tenant —
    the service layer must preserve the isolation the repository
    already enforces, not accidentally bypass it."""

    async def test_cannot_update_a_site_belonging_to_a_different_client(
        self, client_service: ClientService, site_service: SiteService
    ) -> None:
        tenant_id = uuid4()
        client_a = await client_service.create_client(
            tenant_id=tenant_id, name="Client A", client_type=ClientType.RESIDENTIAL
        )
        client_b = await client_service.create_client(
            tenant_id=tenant_id, name="Client B", client_type=ClientType.RESIDENTIAL
        )
        site_x = await site_service.create_site(
            tenant_id=tenant_id,
            client_id=client_b.id,
            label="Site X",
            address=_address(),
        )
        assert site_x.is_primary is True

        with pytest.raises(SiteNotFoundError):
            await site_service.update_site(
                tenant_id=tenant_id,
                client_id=client_a.id,
                site_id=site_x.id,
                is_primary=True,
            )

        # Site X must be completely untouched by the rejected attempt.
        refetched = await site_service.get_site(
            tenant_id=tenant_id, client_id=client_b.id, site_id=site_x.id
        )
        assert refetched.is_primary is True
