"""
tests/integration/test_clients_api.py

Platform Conventions §8's actual integration tier: the real
create_app(), real signed JWTs against a real local JWKS server, real
in-memory repositories. Covers the full clients CRUD lifecycle and —
the mandatory category for client-service specifically (§8) — the
cross-tenant isolation and tenant-claim-spoofing matrix.

Business-metric tests live separately in test_client_metrics.py, not
here — a different concern (observability) from the behavioral tests
in this file, and one that will keep growing (site/contact/JWT
metrics) independently of client CRUD behavior.

Resource creation is inlined at each call site (post + assert 201 +
extract id), not hidden behind a helper — creating a client is one of
the primary behaviors under test in several of these tests, and a
helper would obscure exactly the thing being asserted.

FastAPI/Starlette only run lifespan handlers when TestClient is used
as a context manager (`with TestClient(app) as client:`), not bare
`TestClient(app)` — every test below uses the context-manager form.
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.main import create_app
from tests.integration.auth_helpers import auth_header


class TestClientCrudLifecycle:
    def test_create_then_get_round_trip(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Acme Corp", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            body = create_response.json()
            assert body["name"] == "Acme Corp"
            assert body["client_type"] == "commercial"
            assert body["status"] == "active"
            assert body["sites"] == []
            assert body["contacts"] == []
            assert body["tenant_id"] == tenant_id

            get_response = client.get(f"/v1/clients/{body['id']}", headers=headers)
            assert get_response.status_code == 200
            assert get_response.json() == body

    def test_list_returns_summary_shape_not_full_shape(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Acme", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201

            list_response = client.get("/v1/clients", headers=headers)
            assert list_response.status_code == 200
            body = list_response.json()
            assert body["total"] == 1
            assert body["limit"] == 20
            assert body["offset"] == 0
            item = body["items"][0]
            assert item["name"] == "Acme"
            assert "site_count" in item
            assert "contact_count" in item
            assert "sites" not in item
            assert "contacts" not in item

    def test_update_client(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Old Name", "client_type": "residential"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            patch_response = client.patch(
                f"/v1/clients/{client_id}", json={"name": "New Name"}, headers=headers
            )
            assert patch_response.status_code == 200
            assert patch_response.json()["name"] == "New Name"

    def test_delete_archives_not_hard_deletes(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "To Archive", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            delete_response = client.delete(f"/v1/clients/{client_id}", headers=headers)
            assert delete_response.status_code == 204

            get_response = client.get(f"/v1/clients/{client_id}", headers=headers)
            assert get_response.status_code == 200
            assert get_response.json()["status"] == "archived"

    def test_archived_client_still_appears_in_list(self, settings, keypair):
        """Protects against a future optimization accidentally
        filtering archived clients out of list results — the API
        contract makes no such exclusion, and this is the one test
        that would fail if that assumption were ever silently added."""
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Archived But Listed", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            list_response = client.get("/v1/clients", headers=headers)
            items = list_response.json()["items"]
            assert len(items) == 1
            assert items[0]["id"] == client_id
            assert items[0]["status"] == "archived"

    def test_delete_is_idempotent(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Twice Deleted", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            first = client.delete(f"/v1/clients/{client_id}", headers=headers)
            second = client.delete(f"/v1/clients/{client_id}", headers=headers)
            assert first.status_code == 204
            assert second.status_code == 204

    def test_update_against_archived_client_returns_409(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Will Archive", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]
            client.delete(f"/v1/clients/{client_id}", headers=headers)

            patch_response = client.patch(
                f"/v1/clients/{client_id}",
                json={"name": "Cannot Change"},
                headers=headers,
            )
            assert patch_response.status_code == 409

    def test_archive_via_update_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            patch_response = client.patch(
                f"/v1/clients/{client_id}", json={"status": "archived"}, headers=headers
            )
            assert patch_response.status_code == 409
            assert patch_response.json()["code"] == "archive_via_update_not_allowed"


class TestLimitClamping:
    def test_limit_over_100_clamps_not_rejects(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.get("/v1/clients?limit=500", headers=headers)
            assert response.status_code == 200
            assert response.json()["limit"] == 100

    def test_limit_zero_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.get("/v1/clients?limit=0", headers=headers)
            assert response.status_code == 422

    def test_negative_offset_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.get("/v1/clients?offset=-1", headers=headers)
            assert response.status_code == 422


class TestTenantIdSpoofingRejected:
    """Platform Conventions §5: tenant_id is never accepted from
    request input — the field is forbidden outright, not merely
    checked against the caller's own token. Both variants below
    (spoofed value equal to the caller's own tenant, and spoofed value
    equal to a genuinely different real tenant) must be rejected
    identically — the rule is "forbidden field," not "must match."""

    def test_tenant_id_in_create_body_matching_own_tenant_rejected(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial", "tenant_id": tenant_id},
                headers=headers,
            )
            assert response.status_code == 422

    def test_tenant_id_in_create_body_matching_other_real_tenant_rejected(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        other_tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.post(
                "/v1/clients",
                json={
                    "name": "X",
                    "client_type": "commercial",
                    "tenant_id": other_tenant_id,
                },
                headers=headers,
            )
            assert response.status_code == 422

    def test_tenant_id_in_update_body_rejected(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            response = client.patch(
                f"/v1/clients/{client_id}",
                json={"name": "Y", "tenant_id": str(uuid4())},
                headers=headers,
            )
            assert response.status_code == 422


class TestCrossTenantIsolation:
    """The mandatory category (Platform Conventions §8): tenant A's
    token must never read or modify tenant B's client, even by
    guessing a valid UUID. Proven for GET, PATCH, and DELETE — a
    system that only blocks reads while allowing writes against a
    guessed UUID is still broken."""

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
            create_response = client.post(
                "/v1/clients",
                json={"name": "Tenant A's Client", "client_type": "commercial"},
                headers=headers_a,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            response = client.get(f"/v1/clients/{client_id}", headers=headers_b)
            assert response.status_code == 404

    def test_nonexistent_uuid_returns_404_indistinguishably_from_cross_tenant(
        self, settings, keypair
    ):
        """The architecture deliberately makes "exists but belongs to
        another tenant" and "never existed at all" indistinguishable
        (01-api-contract.md: avoids confirming a client ID's existence
        across tenant boundaries) — this proves the second case
        directly, as its own invariant, not just inferred from the
        cross-tenant case above."""
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.get(f"/v1/clients/{uuid4()}", headers=headers)
            assert response.status_code == 404

    def test_cross_tenant_patch_returns_404(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        headers_a = auth_header(
            private_key, tenant_id=tenant_a, permissions=[CLIENTS_WRITE, CLIENTS_READ]
        )
        headers_b = auth_header(
            private_key, tenant_id=tenant_b, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Tenant A's Client", "client_type": "commercial"},
                headers=headers_a,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            response = client.patch(
                f"/v1/clients/{client_id}", json={"name": "Hijacked"}, headers=headers_b
            )
            assert response.status_code == 404

    def test_cross_tenant_delete_returns_404_and_does_not_actually_archive(
        self, settings, keypair
    ):
        private_key, _public_key = keypair
        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        headers_a = auth_header(
            private_key, tenant_id=tenant_a, permissions=[CLIENTS_WRITE, CLIENTS_READ]
        )
        headers_b = auth_header(
            private_key, tenant_id=tenant_b, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            create_response = client.post(
                "/v1/clients",
                json={"name": "Tenant A's Client", "client_type": "commercial"},
                headers=headers_a,
            )
            assert create_response.status_code == 201
            client_id = create_response.json()["id"]

            delete_response = client.delete(
                f"/v1/clients/{client_id}", headers=headers_b
            )
            assert delete_response.status_code == 404

            # Confirms the isolation actually prevents the mutation,
            # not just returns the right status code while secretly
            # still applying it.
            get_response = client.get(f"/v1/clients/{client_id}", headers=headers_a)
            assert get_response.json()["status"] == "active"

    def test_list_only_returns_own_tenant_clients(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        headers_a = auth_header(
            private_key, tenant_id=tenant_a, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )
        headers_b = auth_header(
            private_key, tenant_id=tenant_b, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            resp_a = client.post(
                "/v1/clients",
                json={"name": "A's Client", "client_type": "commercial"},
                headers=headers_a,
            )
            resp_b = client.post(
                "/v1/clients",
                json={"name": "B's Client", "client_type": "commercial"},
                headers=headers_b,
            )
            assert resp_a.status_code == 201
            assert resp_b.status_code == 201

            list_response = client.get("/v1/clients", headers=headers_a)
            names = [item["name"] for item in list_response.json()["items"]]
            assert names == ["A's Client"]


class TestPermissionEnforcement:
    def test_missing_write_permission_returns_403(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            assert response.status_code == 403

    def test_missing_read_permission_returns_403(self, settings, keypair):
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            response = client.get("/v1/clients", headers=headers)
            assert response.status_code == 403

    def test_missing_token_returns_401(self, settings, keypair):
        with TestClient(create_app(settings=settings)) as client:
            response = client.get("/v1/clients")
            assert response.status_code == 401

    def test_full_permission_set_allows_read_and_write(self, settings, keypair):
        """The expected happy path for a token carrying both
        permissions — documents what "correctly authorized" looks
        like, alongside the two 403 cases above that document what
        "under-authorized" looks like."""
        private_key, _public_key = keypair
        tenant_id = str(uuid4())
        headers = auth_header(
            private_key, tenant_id=tenant_id, permissions=[CLIENTS_READ, CLIENTS_WRITE]
        )

        with TestClient(create_app(settings=settings)) as client:
            get_response = client.get("/v1/clients", headers=headers)
            assert get_response.status_code == 200

            post_response = client.post(
                "/v1/clients",
                json={"name": "X", "client_type": "commercial"},
                headers=headers,
            )
            assert post_response.status_code == 201
