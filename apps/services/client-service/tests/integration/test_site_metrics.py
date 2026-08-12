"""
tests/integration/test_site_metrics.py

Business-metric tests for the sites resource — split from
test_sites_api.py, same reasoning as test_client_metrics.py.

site_delete_contact_nulled_total needs a contact attached to a site to
test meaningfully, but contact HTTP routes don't exist until
feature/client-service-contacts-api. ContactService itself already
exists (built in the original entity-services work), so the
precondition is seeded by calling it directly — via a pre-built
ServiceRegistry handed to create_app(registry=...), exactly the use
case that injectable-registry parameter was designed for. The actual
behavior under test (site deletion nulling the contact) is still
exercised through real HTTP, only the setup bypasses it.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import build_services
from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.main import create_app
from app.metrics.business_metrics import (
    SITE_CREATED_TOTAL,
    SITE_DELETE_CONTACT_NULLED_TOTAL,
)
from app.models.address import Address
from tests.integration.auth_helpers import auth_header
from tests.integration.metrics_helpers import counter_total

_ADDRESS = {
    "line1": "14 Colmore Row",
    "line2": None,
    "city": "Birmingham",
    "postcode": "B3 2QD",
    "country": "UK",
}


class TestSiteMetrics:
    def test_site_created_total_increments(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_client_response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            client_id = create_client_response.json()["id"]

            before = counter_total(SITE_CREATED_TOTAL)
            response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "X", "address": _ADDRESS},
                headers=headers,
            )
            assert response.status_code == 201
            after = counter_total(SITE_CREATED_TOTAL)

            assert after - before == 1

    async def test_site_delete_contact_nulled_total_increments_by_actual_count(
        self, settings, keypair
    ):
        """Exactly one contact is attached to the site under test, and
        a second, unattached contact exists as a control — proving the
        counter tracks the ACTUAL affected count (SiteService.
        delete_site()'s own return value), not simply "some contacts
        existed somewhere for this client". Seeding uses a real
        async test function (pytest.ini's asyncio_mode = auto),
        matching this project's established pattern — not
        asyncio.run() inside a sync test."""
        private_key, _public_key = keypair
        tenant_uuid = uuid4()
        headers = auth_header(
            private_key,
            tenant_id=str(tenant_uuid),
            permissions=[CLIENTS_READ, CLIENTS_WRITE],
        )

        registry = build_services()
        client_obj = await registry.client_service.create_client(
            tenant_id=tenant_uuid, name="X", client_type="commercial"
        )
        site_obj = await registry.site_service.create_site(
            tenant_id=tenant_uuid,
            client_id=client_obj.id,
            label="X",
            address=Address(line1="1 Test St", city="Birmingham", postcode="B1 1AA"),
        )
        await registry.contact_service.create_contact(
            tenant_id=tenant_uuid,
            client_id=client_obj.id,
            site_id=site_obj.id,
            name="Attached Contact",
            email="attached@example.com",
        )
        await registry.contact_service.create_contact(
            tenant_id=tenant_uuid,
            client_id=client_obj.id,
            site_id=None,
            name="Unattached Contact",
            email="unattached@example.com",
        )

        with TestClient(create_app(settings=settings, registry=registry)) as client:
            before = counter_total(SITE_DELETE_CONTACT_NULLED_TOTAL)

            response = client.delete(
                f"/v1/clients/{client_obj.id}/sites/{site_obj.id}", headers=headers
            )
            assert response.status_code == 204

            after = counter_total(SITE_DELETE_CONTACT_NULLED_TOTAL)
            assert after - before == 1
