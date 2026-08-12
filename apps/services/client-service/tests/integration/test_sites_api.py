"""
tests/integration/test_sites_api.py

Platform Conventions §8's real integration tier: the real create_app(),
real signed JWTs, real in-memory repositories. Covers the full sites
CRUD lifecycle nested under a client.

New isolation dimension beyond what clients needed: a site belongs to
a CLIENT, not just a tenant — so beyond tenant A vs tenant B, this
suite also proves site-under-client-A is unreachable via client-B's
URL even within the SAME tenant (01-api-contract.md: "same identical-
404 rationale as the client resource").

DELETE here is a genuine hard delete, unlike client DELETE (archive,
idempotent) — a second DELETE against the same site_id must be 404,
not 204. Proven explicitly, not assumed from the clients pattern.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.main import create_app
from tests.integration.auth_helpers import auth_header

_ADDRESS = {
    "line1": "14 Colmore Row",
    "line2": None,
    "city": "Birmingham",
    "postcode": "B3 2QD",
    "country": "UK",
}


def _create_client(client, headers) -> str:
    response = client.post(
        "/v1/clients",
        json={"name": "Test Client", "client_type": "commercial"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestSiteCrudLifecycle:
    def test_create_then_get_round_trip(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)

            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "Main Warehouse", "address": _ADDRESS},
                headers=headers,
            )
            assert create_response.status_code == 201
            body = create_response.json()
            assert body["label"] == "Main Warehouse"
            assert body["client_id"] == client_id
            assert body["tenant_id"] == tenant_id
            assert body["address"]["city"] == "Birmingham"

            get_response = client.get(
                f"/v1/clients/{client_id}/sites/{body['id']}", headers=headers
            )
            assert get_response.status_code == 200
            assert get_response.json() == body

    def test_first_site_is_auto_primary_regardless_of_request(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "First Site", "address": _ADDRESS},
                headers=headers,
            )
            assert response.status_code == 201
            assert response.json()["is_primary"] is True

    def test_explicit_primary_demotes_previous_holder(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)

            first = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "First Site", "address": _ADDRESS},
                headers=headers,
            )
            first_id = first.json()["id"]
            assert first.json()["is_primary"] is True

            second = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "Second Site", "address": _ADDRESS, "is_primary": True},
                headers=headers,
            )
            assert second.json()["is_primary"] is True

            first_after = client.get(
                f"/v1/clients/{client_id}/sites/{first_id}", headers=headers
            )
            assert first_after.json()["is_primary"] is False

    def test_list_returns_plain_array_not_paginated_envelope(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)
            client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "A Site", "address": _ADDRESS},
                headers=headers,
            )

            response = client.get(f"/v1/clients/{client_id}/sites", headers=headers)
            assert response.status_code == 200
            assert isinstance(response.json(), list)
            assert len(response.json()) == 1

    def test_update_site(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "Old Label", "address": _ADDRESS},
                headers=headers,
            )
            site_id = create_response.json()["id"]

            patch_response = client.patch(
                f"/v1/clients/{client_id}/sites/{site_id}",
                json={"label": "New Label"},
                headers=headers,
            )
            assert patch_response.status_code == 200
            assert patch_response.json()["label"] == "New Label"

    def test_delete_hard_deletes_not_idempotent(self, settings, keypair):
        """The real distinction from client DELETE: a second attempt
        must be 404, not 204."""
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "Deletable", "address": _ADDRESS},
                headers=headers,
            )
            site_id = create_response.json()["id"]

            first_delete = client.delete(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers
            )
            assert first_delete.status_code == 204

            second_delete = client.delete(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers
            )
            assert second_delete.status_code == 404

            get_response = client.get(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers
            )
            assert get_response.status_code == 404


class TestArchivedClientRejection:
    def test_create_site_against_archived_client_returns_409(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "Too Late", "address": _ADDRESS},
                headers=headers,
            )
            assert response.status_code == 409

    def test_update_site_against_archived_client_returns_409(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "X", "address": _ADDRESS},
                headers=headers,
            )
            site_id = create_response.json()["id"]
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            response = client.patch(
                f"/v1/clients/{client_id}/sites/{site_id}",
                json={"label": "Y"},
                headers=headers,
            )
            assert response.status_code == 409

    def test_delete_site_against_archived_client_returns_409(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "X", "address": _ADDRESS},
                headers=headers,
            )
            site_id = create_response.json()["id"]
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            response = client.delete(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers
            )
            assert response.status_code == 409

    def test_reads_succeed_regardless_of_archived_status(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "X", "address": _ADDRESS},
                headers=headers,
            )
            site_id = create_response.json()["id"]
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            get_one = client.get(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers
            )
            get_list = client.get(f"/v1/clients/{client_id}/sites", headers=headers)
            assert get_one.status_code == 200
            assert get_list.status_code == 200


class TestTenantIdSpoofingRejected:
    def test_tenant_id_in_create_body_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "X", "address": _ADDRESS, "tenant_id": tenant_id},
                headers=headers,
            )
            assert response.status_code == 422

    def test_undeclared_address_field_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={
                    "label": "X",
                    "address": {**_ADDRESS, "extra_field": "not allowed"},
                },
                headers=headers,
            )
            assert response.status_code == 422

    def test_blank_label_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "   ", "address": _ADDRESS},
                headers=headers,
            )
            assert response.status_code == 422


class TestCrossTenantIsolation:
    def test_cross_tenant_get_returns_404(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        headers_a = auth_header(
            private_key, tenant_id=tenant_a, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )
        headers_b = auth_header(
            private_key, tenant_id=tenant_b, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers_a)
            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "A's Site", "address": _ADDRESS},
                headers=headers_a,
            )
            site_id = create_response.json()["id"]

            response = client.get(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers_b
            )
            assert response.status_code == 404

    def test_cross_tenant_delete_returns_404_and_does_not_actually_delete(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        headers_a = auth_header(
            private_key, tenant_id=tenant_a, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )
        headers_b = auth_header(
            private_key, tenant_id=tenant_b, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, headers_a)
            create_response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "A's Site", "address": _ADDRESS},
                headers=headers_a,
            )
            site_id = create_response.json()["id"]

            delete_response = client.delete(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers_b
            )
            assert delete_response.status_code == 404

            get_response = client.get(
                f"/v1/clients/{client_id}/sites/{site_id}", headers=headers_a
            )
            assert get_response.status_code == 200


class TestCrossClientIsolation:
    """New isolation dimension beyond clients: a site belongs to one
    client, not just one tenant. Same tenant, wrong client — must be
    404, the identical rationale 01-api-contract.md gives for the
    cross-tenant case."""

    def test_site_under_client_a_unreachable_via_client_b_same_tenant(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_a_id = _create_client(client, headers)
            client_b_id = _create_client(client, headers)

            create_response = client.post(
                f"/v1/clients/{client_a_id}/sites",
                json={"label": "A's Site", "address": _ADDRESS},
                headers=headers,
            )
            site_id = create_response.json()["id"]

            response = client.get(
                f"/v1/clients/{client_b_id}/sites/{site_id}", headers=headers
            )
            assert response.status_code == 404

    def test_site_delete_via_wrong_client_returns_404_and_does_not_delete(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_a_id = _create_client(client, headers)
            client_b_id = _create_client(client, headers)

            create_response = client.post(
                f"/v1/clients/{client_a_id}/sites",
                json={"label": "A's Site", "address": _ADDRESS},
                headers=headers,
            )
            site_id = create_response.json()["id"]

            delete_response = client.delete(
                f"/v1/clients/{client_b_id}/sites/{site_id}", headers=headers
            )
            assert delete_response.status_code == 404

            get_response = client.get(
                f"/v1/clients/{client_a_id}/sites/{site_id}", headers=headers
            )
            assert get_response.status_code == 200


class TestPermissionEnforcement:
    def test_missing_write_permission_returns_403(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        write_headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )
        read_only_headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, write_headers)

            response = client.post(
                f"/v1/clients/{client_id}/sites",
                json={"label": "X", "address": _ADDRESS},
                headers=read_only_headers,
            )
            assert response.status_code == 403

    def test_missing_read_permission_returns_403(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        write_headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )
        write_only_headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client(client, write_headers)

            response = client.get(
                f"/v1/clients/{client_id}/sites", headers=write_only_headers
            )
            assert response.status_code == 403
