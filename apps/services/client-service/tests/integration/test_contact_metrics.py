"""
tests/integration/test_contact_metrics.py

Business-metric tests for the contacts resource — split from
test_contacts_api.py, same reasoning as test_client_metrics.py and
test_site_metrics.py.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.main import create_app
from app.metrics.business_metrics import CONTACT_CREATED_TOTAL
from tests.integration.auth_helpers import auth_header
from tests.integration.metrics_helpers import counter_total


class TestContactMetrics:
    def test_contact_created_total_increments(self, settings, keypair):
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

            before = counter_total(CONTACT_CREATED_TOTAL)
            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            assert response.status_code == 201
            after = counter_total(CONTACT_CREATED_TOTAL)

            assert after - before == 1
