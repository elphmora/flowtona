"""
tests/unit/services/test_contact_service.py

Service-layer tests for ContactService — same is_primary orchestration
pattern as SiteService.
"""

from uuid import uuid4

import pytest

from app.exceptions.client import ClientArchivedError, ClientNotFoundError
from app.exceptions.contact import (
    ContactNotFoundError,
    ContactRequiresEmailOrPhoneError,
)
from app.exceptions.site import SiteNotFoundError
from app.models.address import Address
from app.models.enums import ClientType
from app.services.client_service import ClientService
from app.services.contact_service import ContactService
from app.services.site_service import SiteService


def _make_address() -> Address:
    return Address(line1="1 Test St", city="Birmingham", postcode="B1 1AA")


async def _make_client(client_service: ClientService):
    return await client_service.create_client(
        tenant_id=uuid4(), name="Test Co.", client_type=ClientType.COMMERCIAL
    )


class TestCreateContact:
    async def test_first_contact_is_auto_primary(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="Priya",
            phone="+44 121 000 0000",
        )
        assert contact.is_primary is True

    async def test_explicit_primary_on_second_contact_demotes_first(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        first = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0001",
        )
        assert first.is_primary is True

        second = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="B",
            phone="+44 121 000 0002",
            is_primary=True,
        )

        all_contacts = await contact_service.list_contacts(
            tenant_id=client.tenant_id, client_id=client.id
        )
        primary_contacts = [c for c in all_contacts if c.is_primary]
        assert len(primary_contacts) == 1
        assert primary_contacts[0].id == second.id

    async def test_requires_writable_client_raises_when_archived(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        with pytest.raises(ClientArchivedError):
            await contact_service.create_contact(
                tenant_id=client.tenant_id,
                client_id=client.id,
                name="A",
                phone="+44 121 000 0000",
            )

    async def test_requires_writable_client_raises_when_client_missing(
        self, contact_service: ContactService
    ) -> None:
        with pytest.raises(ClientNotFoundError):
            await contact_service.create_contact(
                tenant_id=uuid4(), client_id=uuid4(), name="A", phone="+44 121 000 0000"
            )

    async def test_site_id_belonging_to_different_client_raises_site_not_found(
        self,
        client_service: ClientService,
        contact_service: ContactService,
        site_service: SiteService,
    ) -> None:
        client_a = await _make_client(client_service)
        client_b = await _make_client(client_service)
        site_under_b = await site_service.create_site(
            tenant_id=client_b.tenant_id,
            client_id=client_b.id,
            label="B's Site",
            address=_make_address(),
        )

        with pytest.raises(SiteNotFoundError):
            await contact_service.create_contact(
                tenant_id=client_a.tenant_id,
                client_id=client_a.id,
                site_id=site_under_b.id,
                name="A",
                phone="+44 121 000 0000",
            )


class TestGetContact:
    async def test_missing_contact_raises_contact_not_found(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        with pytest.raises(ContactNotFoundError):
            await contact_service.get_contact(
                tenant_id=client.tenant_id, client_id=client.id, contact_id=uuid4()
            )


class TestListContacts:
    async def test_site_id_filter_delegates_to_repository(
        self,
        client_service: ClientService,
        contact_service: ContactService,
        site_service: SiteService,
    ) -> None:
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="X",
            address=_make_address(),
        )
        await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            site_id=site.id,
            name="A",
            phone="+44 121 000 0001",
        )
        await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="B",
            email="b@example.com",
        )

        filtered = await contact_service.list_contacts(
            tenant_id=client.tenant_id, client_id=client.id, site_id=site.id
        )
        assert len(filtered) == 1
        assert filtered[0].name == "A"


class TestUpdateContact:
    async def test_setting_primary_true_demotes_current_primary(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        first = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0001",
        )
        second = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="B",
            phone="+44 121 000 0002",
        )
        assert first.is_primary is True
        assert second.is_primary is False

        await contact_service.update_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            contact_id=second.id,
            is_primary=True,
        )

        all_contacts = await contact_service.list_contacts(
            tenant_id=client.tenant_id, client_id=client.id
        )
        primary_contacts = [c for c in all_contacts if c.is_primary]
        assert len(primary_contacts) == 1
        assert primary_contacts[0].id == second.id

    async def test_requires_writable_client_raises_when_archived(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0000",
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        with pytest.raises(ClientArchivedError):
            await contact_service.update_contact(
                tenant_id=client.tenant_id,
                client_id=client.id,
                contact_id=contact.id,
                name="Renamed",
            )

    async def test_omitted_field_preserves_existing_value(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        """UNSET (the real default) must leave role untouched — this
        is the specific fix: previously None meant both "omitted" and
        "clear", so this distinction didn't exist."""
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0000",
            role="Site Manager",
        )

        updated = await contact_service.update_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            contact_id=contact.id,
            name="A Renamed",
        )

        assert updated.role == "Site Manager"

    async def test_explicit_null_clears_role(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0000",
            role="Site Manager",
        )

        updated = await contact_service.update_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            contact_id=contact.id,
            role=None,
        )

        assert updated.role is None

    async def test_explicit_null_detaches_contact_from_site(
        self,
        client_service: ClientService,
        contact_service: ContactService,
        site_service: SiteService,
    ) -> None:
        """The exact scenario this whole fix exists for: a contact
        attached to a site must be detachable via PATCH by explicitly
        sending site_id: null — impossible under the old None-means-
        omitted-or-clear implementation."""
        client = await _make_client(client_service)
        site = await site_service.create_site(
            tenant_id=client.tenant_id,
            client_id=client.id,
            label="X",
            address=_make_address(),
        )
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            site_id=site.id,
            name="A",
            phone="+44 121 000 0000",
        )
        assert contact.site_id == site.id

        updated = await contact_service.update_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            contact_id=contact.id,
            site_id=None,
        )

        assert updated.site_id is None

    async def test_update_site_id_belonging_to_different_client_raises_site_not_found(
        self,
        client_service: ClientService,
        contact_service: ContactService,
        site_service: SiteService,
    ) -> None:
        client_a = await _make_client(client_service)
        client_b = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client_a.tenant_id,
            client_id=client_a.id,
            name="A",
            phone="+44 121 000 0000",
        )
        site_under_b = await site_service.create_site(
            tenant_id=client_b.tenant_id,
            client_id=client_b.id,
            label="B's Site",
            address=_make_address(),
        )

        with pytest.raises(SiteNotFoundError):
            await contact_service.update_contact(
                tenant_id=client_a.tenant_id,
                client_id=client_a.id,
                contact_id=contact.id,
                site_id=site_under_b.id,
            )

    async def test_clearing_email_when_phone_absent_raises_invariant_error(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        """The merged-state check: this contact has ONLY email — the
        request body alone (just {"email": null}) can't tell whether
        phone exists; the service must check against the contact's
        actual current state."""
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            email="a@example.com",
        )

        with pytest.raises(ContactRequiresEmailOrPhoneError):
            await contact_service.update_contact(
                tenant_id=client.tenant_id,
                client_id=client.id,
                contact_id=contact.id,
                email=None,
            )

    async def test_clearing_email_when_phone_present_succeeds(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            email="a@example.com",
            phone="+44 121 000 0000",
        )

        updated = await contact_service.update_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            contact_id=contact.id,
            email=None,
        )

        assert updated.email is None
        assert updated.phone == "+44 121 000 0000"

    async def test_failed_invariant_check_does_not_demote_other_contact(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        """The ordering fix: if this update is ultimately rejected
        (email/phone invariant violated), a DIFFERENT contact's
        is_primary must not have been silently demoted as a side
        effect of the attempt. Validation must happen before any
        side-effecting write, not after."""
        client = await _make_client(client_service)
        first = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0001",
        )
        second = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="B",
            email="b@example.com",
        )
        assert first.is_primary is True
        assert second.is_primary is False

        with pytest.raises(ContactRequiresEmailOrPhoneError):
            await contact_service.update_contact(
                tenant_id=client.tenant_id,
                client_id=client.id,
                contact_id=second.id,
                email=None,
                is_primary=True,
            )

        # first must STILL be primary — the rejected update must not
        # have demoted it as a partial side effect.
        refreshed_first = await contact_service.get_contact(
            tenant_id=client.tenant_id, client_id=client.id, contact_id=first.id
        )
        assert refreshed_first.is_primary is True


class TestDeleteContact:
    async def test_deletes_contact(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0000",
        )
        await contact_service.delete_contact(
            tenant_id=client.tenant_id, client_id=client.id, contact_id=contact.id
        )
        with pytest.raises(ContactNotFoundError):
            await contact_service.get_contact(
                tenant_id=client.tenant_id, client_id=client.id, contact_id=contact.id
            )

    async def test_requires_writable_client_raises_when_archived(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0000",
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        with pytest.raises(ClientArchivedError):
            await contact_service.delete_contact(
                tenant_id=client.tenant_id, client_id=client.id, contact_id=contact.id
            )

    async def test_missing_contact_raises_contact_not_found(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        with pytest.raises(ContactNotFoundError):
            await contact_service.delete_contact(
                tenant_id=client.tenant_id, client_id=client.id, contact_id=uuid4()
            )


class TestArchivedClientRemainsReadable:
    """Decision 5: archived means immutable, not invisible."""

    async def test_get_contact_still_works_after_client_archived(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        contact = await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0000",
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        found = await contact_service.get_contact(
            tenant_id=client.tenant_id, client_id=client.id, contact_id=contact.id
        )
        assert found.id == contact.id

    async def test_list_contacts_still_works_after_client_archived(
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            name="A",
            phone="+44 121 000 0000",
        )
        await client_service.archive_client(
            tenant_id=client.tenant_id, client_id=client.id
        )

        contacts = await contact_service.list_contacts(
            tenant_id=client.tenant_id, client_id=client.id
        )
        assert len(contacts) == 1
