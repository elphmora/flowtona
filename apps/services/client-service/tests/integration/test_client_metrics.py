"""
tests/integration/test_client_metrics.py

Business-metric tests for the clients resource, split from
test_clients_api.py — a different concern (observability) from CRUD/
tenant-isolation/permission behavior, and one that will keep growing
independently (site metrics, contact metrics, job metrics, invoice
metrics — each resource family gets its own module here, not one
ever-growing shared file).

Counters (app/metrics/business_metrics.py) are module-level Prometheus
singletons that persist and accumulate across every test in the same
process — every assertion below reads a delta (before -> after), never
an absolute total, same pattern established in
tests/unit/middleware/test_metrics.py.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.main import create_app
from app.metrics.business_metrics import (
    CLIENT_ARCHIVED_TOTAL,
    CLIENT_ARCHIVED_WRITE_REJECTED_TOTAL,
    CLIENT_CREATED_TOTAL,
    PERMISSION_DENIED_TOTAL,
)
from tests.integration.auth_helpers import auth_header
from tests.integration.metrics_helpers import counter_total, counter_total_for_label


class TestClientMetrics:
    def test_client_created_total_increments(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            before = counter_total(CLIENT_CREATED_TOTAL)
            response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            assert response.status_code == 201
            after = counter_total(CLIENT_CREATED_TOTAL)
            assert after - before == 1

    def test_client_archived_total_increments_once_not_twice_on_idempotent_retry(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_WRITE, CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            before = counter_total(CLIENT_ARCHIVED_TOTAL)
            client.delete(f"/v1/clients/{client_id}", headers=headers)
            client.delete(
                f"/v1/clients/{client_id}", headers=headers
            )  # idempotent retry
            after = counter_total(CLIENT_ARCHIVED_TOTAL)
            assert after - before == 1

    def test_archived_write_rejected_increments_from_patch_path(
        self, settings, keypair
    ):
        """Proves the fix specifically: PATCH against an archived
        client goes through update_client()'s OWN archived-rejection
        path, not require_writable_client() — both must increment this
        counter, and this test covers the one that was originally
        missed."""
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_WRITE, CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            before = counter_total(CLIENT_ARCHIVED_WRITE_REJECTED_TOTAL)
            client.patch(
                f"/v1/clients/{client_id}", json={"name": "Y"}, headers=headers
            )
            after = counter_total(CLIENT_ARCHIVED_WRITE_REJECTED_TOTAL)
            assert after - before == 1

    def test_permission_denied_total_increments_with_correct_label(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            before = counter_total_for_label(
                PERMISSION_DENIED_TOTAL, permission=CLIENTS_WRITE
            )
            client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            after = counter_total_for_label(
                PERMISSION_DENIED_TOTAL, permission=CLIENTS_WRITE
            )
            assert after - before == 1
