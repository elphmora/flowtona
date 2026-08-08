"""
tests/unit/services/test_contact_service.py

Service-layer tests for ContactService — same is_primary orchestration
pattern as SiteService.
"""

from uuid import uuid4

import pytest

from app.exceptions.client import ClientArchivedError, ClientNotFoundError
from app.exceptions.contact import ContactNotFoundError
from app.models.enums import ClientType
from app.services.client_service import ClientService
from app.services.contact_service import ContactService


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
        self, client_service: ClientService, contact_service: ContactService
    ) -> None:
        client = await _make_client(client_service)
        site_id = uuid4()
        await contact_service.create_contact(
            tenant_id=client.tenant_id,
            client_id=client.id,
            site_id=site_id,
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
            tenant_id=client.tenant_id, client_id=client.id, site_id=site_id
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
