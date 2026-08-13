"""
tests/integration/test_contacts_api.py

Platform Conventions §8's real integration tier. Covers the full
contacts CRUD lifecycle, plus everything this branch's service-layer
rework specifically exists to prove works correctly through real HTTP,
not just at the unit tier:

- site ownership validation (site_id belonging to a different client
  is rejected, not silently accepted)
- three-state PATCH semantics (omitted / explicit null / real value)
  resolved correctly from real JSON request bodies, not just from
  Python call sites
- the merged-state email/phone invariant, including the specific case
  a request body alone cannot validate
- the `?site_id=` filter's two distinct outcomes: malformed UUID is
  422, well-formed-but-non-matching is 200 [] — proven as genuinely
  different code paths, not assumed
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


def _create_client_obj(client, headers) -> str:
    response = client.post(
        "/v1/clients",
        json={"name": "Test Client", "client_type": "commercial"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_site(client, headers, client_id: str) -> str:
    response = client.post(
        f"/v1/clients/{client_id}/sites",
        json={"label": "A Site", "address": _ADDRESS},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestContactCrudLifecycle:
    def test_create_then_get_round_trip(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "Priya Shah", "email": "priya@example.com"},
                headers=headers,
            )
            assert create_response.status_code == 201
            body = create_response.json()
            assert body["name"] == "Priya Shah"
            assert body["email"] == "priya@example.com"
            assert body["site_id"] is None
            assert body["tenant_id"] == tenant_id

            get_response = client.get(
                f"/v1/clients/{client_id}/contacts/{body['id']}", headers=headers
            )
            assert get_response.status_code == 200
            assert get_response.json() == body

    def test_create_client_level_contact_without_site_id(self, settings, keypair):
        """site_id omitted -> client-level contact, not tied to any
        site — explicitly a legitimate case, not an error."""
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "Billing", "phone": "+44 121 000 0000"},
                headers=headers,
            )
            assert response.status_code == 201
            assert response.json()["site_id"] is None

    def test_create_contact_attached_to_site(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            site_id = _create_site(client, headers, client_id)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com", "site_id": site_id},
                headers=headers,
            )
            assert response.status_code == 201
            assert response.json()["site_id"] == site_id

    def test_first_contact_is_auto_primary(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            assert response.json()["is_primary"] is True

    def test_list_returns_plain_array(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )

            response = client.get(f"/v1/clients/{client_id}/contacts", headers=headers)
            assert response.status_code == 200
            assert isinstance(response.json(), list)
            assert len(response.json()) == 1

    def test_delete_contact(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            contact_id = create_response.json()["id"]

            delete_response = client.delete(
                f"/v1/clients/{client_id}/contacts/{contact_id}", headers=headers
            )
            assert delete_response.status_code == 204

            get_response = client.get(
                f"/v1/clients/{client_id}/contacts/{contact_id}", headers=headers
            )
            assert get_response.status_code == 404


class TestValidationErrors:
    def test_blank_name_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "   ", "email": "a@example.com"},
                headers=headers,
            )
            assert response.status_code == 422

    def test_neither_email_nor_phone_rejected_at_create(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A"},
                headers=headers,
            )
            assert response.status_code == 422

    def test_malformed_email_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "not-an-email"},
                headers=headers,
            )
            assert response.status_code == 422

    def test_tenant_id_in_body_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com", "tenant_id": tenant_id},
                headers=headers,
            )
            assert response.status_code == 422


class TestSiteOwnershipValidation:
    """The first real gap this branch closed: site_id must actually
    belong to this client, not just be a well-formed UUID."""

    def test_create_with_site_id_from_different_client_returns_404(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_a_id = _create_client_obj(client, headers)
            client_b_id = _create_client_obj(client, headers)
            site_under_b = _create_site(client, headers, client_b_id)

            response = client.post(
                f"/v1/clients/{client_a_id}/contacts",
                json={"name": "A", "email": "a@example.com", "site_id": site_under_b},
                headers=headers,
            )
            assert response.status_code == 404

    def test_update_site_id_to_different_clients_site_returns_404(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_a_id = _create_client_obj(client, headers)
            client_b_id = _create_client_obj(client, headers)
            site_under_b = _create_site(client, headers, client_b_id)

            create_response = client.post(
                f"/v1/clients/{client_a_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            contact_id = create_response.json()["id"]

            response = client.patch(
                f"/v1/clients/{client_a_id}/contacts/{contact_id}",
                json={"site_id": site_under_b},
                headers=headers,
            )
            assert response.status_code == 404


class TestPatchThreeStateSemantics:
    """The second real gap this branch closed, proven through real
    JSON request bodies, not just Python call sites."""

    def test_omitted_field_preserves_existing_value(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com", "role": "Site Manager"},
                headers=headers,
            )
            contact_id = create_response.json()["id"]

            patch_response = client.patch(
                f"/v1/clients/{client_id}/contacts/{contact_id}",
                json={"name": "A Renamed"},
                headers=headers,
            )
            assert patch_response.status_code == 200
            assert patch_response.json()["role"] == "Site Manager"

    def test_explicit_null_clears_role(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com", "role": "Site Manager"},
                headers=headers,
            )
            contact_id = create_response.json()["id"]

            patch_response = client.patch(
                f"/v1/clients/{client_id}/contacts/{contact_id}",
                json={"role": None},
                headers=headers,
            )
            assert patch_response.status_code == 200
            assert patch_response.json()["role"] is None

    def test_explicit_null_site_id_detaches_from_site(self, settings, keypair):
        """The exact scenario the whole UNSET fix exists for, now
        proven via a real JSON PATCH body — {"site_id": null}."""
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            site_id = _create_site(client, headers, client_id)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com", "site_id": site_id},
                headers=headers,
            )
            contact_id = create_response.json()["id"]
            assert create_response.json()["site_id"] == site_id

            patch_response = client.patch(
                f"/v1/clients/{client_id}/contacts/{contact_id}",
                json={"site_id": None},
                headers=headers,
            )
            assert patch_response.status_code == 200
            assert patch_response.json()["site_id"] is None


class TestMergedStateInvariant:
    def test_clearing_email_when_phone_absent_returns_422(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            contact_id = create_response.json()["id"]

            response = client.patch(
                f"/v1/clients/{client_id}/contacts/{contact_id}",
                json={"email": None},
                headers=headers,
            )
            assert response.status_code == 422
            assert response.json()["code"] == "contact_requires_email_or_phone"

    def test_clearing_email_when_phone_present_succeeds(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={
                    "name": "A",
                    "email": "a@example.com",
                    "phone": "+44 121 000 0000",
                },
                headers=headers,
            )
            contact_id = create_response.json()["id"]

            response = client.patch(
                f"/v1/clients/{client_id}/contacts/{contact_id}",
                json={"email": None},
                headers=headers,
            )
            assert response.status_code == 200
            assert response.json()["email"] is None
            assert response.json()["phone"] == "+44 121 000 0000"


class TestSiteIdFilterBehavior:
    """Two genuinely different outcomes for what look like similar
    "bad" filter values — proven as distinct code paths."""

    def test_malformed_site_id_returns_422(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)

            response = client.get(
                f"/v1/clients/{client_id}/contacts?site_id=not-a-uuid", headers=headers
            )
            assert response.status_code == 422

    def test_well_formed_non_matching_site_id_returns_empty_list(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )

            response = client.get(
                f"/v1/clients/{client_id}/contacts?site_id={uuid4()}", headers=headers
            )
            assert response.status_code == 200
            assert response.json() == []

    def test_omitted_site_id_returns_all_contacts(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            site_id = _create_site(client, headers, client_id)
            client.post(
                f"/v1/clients/{client_id}/contacts",
                json={
                    "name": "Site Contact",
                    "email": "s@example.com",
                    "site_id": site_id,
                },
                headers=headers,
            )
            client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "Client Contact", "email": "c@example.com"},
                headers=headers,
            )

            response = client.get(f"/v1/clients/{client_id}/contacts", headers=headers)
            assert len(response.json()) == 2


class TestArchivedClientRejection:
    def test_create_against_archived_client_returns_409(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            assert response.status_code == 409

    def test_reads_succeed_regardless_of_archived_status(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_id = _create_client_obj(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            contact_id = create_response.json()["id"]
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            get_one = client.get(
                f"/v1/clients/{client_id}/contacts/{contact_id}", headers=headers
            )
            get_list = client.get(f"/v1/clients/{client_id}/contacts", headers=headers)
            assert get_one.status_code == 200
            assert get_list.status_code == 200


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
            client_id = _create_client_obj(client, headers_a)
            create_response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers_a,
            )
            contact_id = create_response.json()["id"]

            response = client.get(
                f"/v1/clients/{client_id}/contacts/{contact_id}", headers=headers_b
            )
            assert response.status_code == 404


class TestCrossClientIsolation:
    def test_contact_under_client_a_unreachable_via_client_b(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            client_a_id = _create_client_obj(client, headers)
            client_b_id = _create_client_obj(client, headers)
            create_response = client.post(
                f"/v1/clients/{client_a_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=headers,
            )
            contact_id = create_response.json()["id"]

            response = client.get(
                f"/v1/clients/{client_b_id}/contacts/{contact_id}", headers=headers
            )
            assert response.status_code == 404


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
            client_id = _create_client_obj(client, write_headers)

            response = client.post(
                f"/v1/clients/{client_id}/contacts",
                json={"name": "A", "email": "a@example.com"},
                headers=read_only_headers,
            )
            assert response.status_code == 403
