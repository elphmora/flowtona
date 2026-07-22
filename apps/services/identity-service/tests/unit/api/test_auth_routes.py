"""tests/unit/api/test_auth_routes.py

End-to-end HTTP tests for account-entry and session routes: real
requests through a real FastAPI app, a real (in-memory) AuthService,
and real RFC 9457 error responses — not just unit tests of route
functions in isolation.

Covers the account-entry and session-lifecycle HTTP endpoints.
Verification and invitation routes are added in their own PRs.

Tests needing to set up extra state directly via `registry` (e.g. a
second membership) are async, matching this codebase's established
pattern — TestClient itself works fine called from inside an async
test, so there's no need for asyncio.run() workarounds.

IMPORTANT: signup_body["user"]["id"] is a STRING (parsed from JSON
over HTTP) — it must be converted via UUID(...) before being passed as
a user_id= argument to any registry service call. Repositories don't
coerce or validate types, so a membership created with a raw string
user_id silently becomes unreachable by any query using the equivalent
UUID object (and vice versa), even though they represent "the same"
user. This bit us directly: three tests were creating a second
membership with a string user_id, which meant AuthService.login()
(which always queries with a real UUID from the fetched User object)
could never see it.
"""

from uuid import UUID

import pytest

from app.constants.roles import Role


def signup(
    client,
    *,
    email="dana@example.com",
    password="hunter22",
    display_name="Dana",
    tenant_label="Dana's Plumbing",
):
    """Submit a signup request and return the full HTTP response.

    Returning the response lets callers assert on status codes as well
    as the response body. Keyword-only arguments keep call sites
    explicit and allow future optional request fields without breaking
    callers."""
    return client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": password,
            "display_name": display_name,
            "tenant_label": tenant_label,
        },
    )


class TestSignup:
    def test_returns_201(self, client):
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": "dana@example.com",
                "password": "hunter22",
                "display_name": "Dana",
                "tenant_label": "Dana's Plumbing",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["result"] == "authenticated"
        assert body["user"]["email"] == "dana@example.com"
        assert body["tenant"]["tenant_label"] == "Dana's Plumbing"
        assert body["membership"]["role"] == "owner"
        assert body["access_token"]
        assert body["refresh_token"]
        assert "password_hash" not in response.text

    def test_duplicate_email_returns_conflict(self, client):
        payload = {
            "email": "dana@example.com",
            "password": "hunter22",
            "display_name": "Dana",
            "tenant_label": "Dana's Plumbing",
        }
        client.post("/v1/auth/signup", json=payload)

        response = client.post("/v1/auth/signup", json=payload)

        assert response.status_code == 409
        assert response.json()["code"] == "email_already_registered"

    def test_invalid_email_returns_validation_error(self, client):
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": "not-an-email",
                "password": "hunter22",
                "display_name": "Dana",
                "tenant_label": "Dana's Plumbing",
            },
        )

        assert response.status_code == 422
        assert response.json()["code"] == "validation_failed"

    def test_missing_field_returns_validation_error(self, client):
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": "dana@example.com",
                "password": "hunter22",
                "display_name": "Dana",
                # tenant_label omitted
            },
        )

        assert response.status_code == 422

    def test_whitespace_only_display_name_returns_validation_error(self, client):
        """Confirms StringConstraints(strip_whitespace=True) actually
        takes effect over real HTTP, not just in schema-level unit
        tests — this is the HTTP-contract counterpart to those."""
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": "dana@example.com",
                "password": "hunter22",
                "display_name": "   ",
                "tenant_label": "Dana's Plumbing",
            },
        )

        assert response.status_code == 422

    def test_whitespace_only_tenant_label_returns_validation_error(self, client):
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": "dana@example.com",
                "password": "hunter22",
                "display_name": "Dana",
                "tenant_label": "   ",
            },
        )

        assert response.status_code == 422

    def test_whitespace_only_password_returns_validation_error(self, client):
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": "dana@example.com",
                "password": "        ",
                "display_name": "Dana",
                "tenant_label": "Dana's Plumbing",
            },
        )

        assert response.status_code == 422


class TestLogin:
    pytestmark = pytest.mark.asyncio

    async def test_returns_authenticated_session(self, client):
        signup(client)

        response = client.post(
            "/v1/auth/login", json={"email": "dana@example.com", "password": "hunter22"}
        )

        assert response.status_code == 200
        assert response.json()["result"] == "authenticated"

    async def test_wrong_password_returns_invalid_credentials(self, client):
        signup(client)

        response = client.post(
            "/v1/auth/login", json={"email": "dana@example.com", "password": "wrong"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    async def test_unknown_email_returns_same_error_as_wrong_password(self, client):
        """The two must be indistinguishable over HTTP too — same
        status, same code, same detail — to avoid user enumeration."""
        signup(client)

        wrong_password = client.post(
            "/v1/auth/login", json={"email": "dana@example.com", "password": "wrong"}
        ).json()
        unknown_email = client.post(
            "/v1/auth/login",
            json={"email": "never-signed-up@example.com", "password": "anything"},
        ).json()

        assert wrong_password["code"] == unknown_email["code"]
        assert wrong_password["detail"] == unknown_email["detail"]

    async def test_multiple_memberships_returns_tenant_selection_required(
        self, client, registry
    ):
        signup_body = signup(client).json()
        user_id = UUID(signup_body["user"]["id"])
        other = await registry.tenant_service.create(tenant_label="Second Business")
        await registry.membership_service.create(
            user_id=user_id,
            tenant_id=other.id,
            role=Role.TECHNICIAN,
        )

        response = client.post(
            "/v1/auth/login", json={"email": "dana@example.com", "password": "hunter22"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["result"] == "tenant_selection_required"
        assert body["preauth_token"]

    async def test_zero_memberships_returns_no_active_membership(
        self, client, registry
    ):
        await registry.user_service.create(
            email="orphan@example.com", password="hunter22", display_name="Orphan"
        )

        response = client.post(
            "/v1/auth/login",
            json={"email": "orphan@example.com", "password": "hunter22"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "no_active_membership"


class TestSelectTenant:
    pytestmark = pytest.mark.asyncio

    async def test_returns_authenticated_session(self, client, registry):
        signup_body = signup(client).json()
        user_id = UUID(signup_body["user"]["id"])
        other_tenant = await registry.tenant_service.create(
            tenant_label="Second Business"
        )
        await registry.membership_service.create(
            user_id=user_id,
            tenant_id=other_tenant.id,
            role=Role.DISPATCHER,
        )
        login_body = client.post(
            "/v1/auth/login",
            json={"email": "dana@example.com", "password": "hunter22"},
        ).json()
        assert login_body["result"] == "tenant_selection_required"

        response = client.post(
            "/v1/auth/select-tenant",
            json={
                "preauth_token": login_body["preauth_token"],
                "tenant_id": str(other_tenant.id),
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["result"] == "authenticated"
        assert body["tenant"]["id"] == str(other_tenant.id)
        assert body["membership"]["role"] == "dispatcher"

    async def test_invalid_preauth_token_returns_401(self, client):
        response = client.post(
            "/v1/auth/select-tenant",
            json={
                "preauth_token": "not-a-real-token",
                "tenant_id": "11111111-1111-1111-1111-111111111111",
            },
        )

        assert response.status_code == 401

    async def test_nonexistent_membership_returns_403(self, client, registry):
        signup_body = signup(client).json()
        user_id = UUID(signup_body["user"]["id"])
        other_tenant = await registry.tenant_service.create(
            tenant_label="Second Business"
        )
        await registry.membership_service.create(
            user_id=user_id,
            tenant_id=other_tenant.id,
            role=Role.DISPATCHER,
        )
        login_body = client.post(
            "/v1/auth/login",
            json={"email": "dana@example.com", "password": "hunter22"},
        ).json()
        unrelated_tenant = await registry.tenant_service.create(
            tenant_label="Not Dana's"
        )

        response = client.post(
            "/v1/auth/select-tenant",
            json={
                "preauth_token": login_body["preauth_token"],
                "tenant_id": str(unrelated_tenant.id),
            },
        )

        assert response.status_code == 403


class TestRefresh:
    pytestmark = pytest.mark.asyncio

    async def test_returns_new_tokens(self, client):
        signup_body = signup(client).json()

        response = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": signup_body["refresh_token"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["result"] == "authenticated"
        assert body["refresh_token"] != signup_body["refresh_token"]
        assert body["access_token"] != signup_body["access_token"]
        assert body["user"]["id"] == signup_body["user"]["id"]

    async def test_invalid_token_returns_401(self, client):
        response = client.post(
            "/v1/auth/refresh", json={"refresh_token": "not-a-real-token"}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_refresh_token"

    async def test_reused_token_returns_401_reuse_detected(self, client):
        signup_body = signup(client).json()
        client.post(
            "/v1/auth/refresh", json={"refresh_token": signup_body["refresh_token"]}
        )

        # Reusing the OLD (now-rotated) token — the actual theft scenario.
        response = client.post(
            "/v1/auth/refresh", json={"refresh_token": signup_body["refresh_token"]}
        )

        assert response.status_code == 401
        assert response.json()["code"] == "token_reuse_detected"

    async def test_empty_token_returns_validation_error(self, client):
        response = client.post("/v1/auth/refresh", json={"refresh_token": ""})

        assert response.status_code == 422


class TestLogout:
    pytestmark = pytest.mark.asyncio

    async def test_returns_204_with_no_body(self, client):
        signup_body = signup(client).json()

        response = client.post(
            "/v1/auth/logout",
            json={"refresh_token": signup_body["refresh_token"]},
        )

        assert response.status_code == 204
        assert response.text == ""

    async def test_revokes_the_session(self, client):
        signup_body = signup(client).json()
        client.post(
            "/v1/auth/logout",
            json={"refresh_token": signup_body["refresh_token"]},
        )

        response = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": signup_body["refresh_token"]},
        )

        assert response.status_code == 401

    async def test_is_idempotent_for_unknown_token(self, client):
        response = client.post(
            "/v1/auth/logout", json={"refresh_token": "never-issued"}
        )

        assert response.status_code == 204


class TestLogoutAllForTenant:
    pytestmark = pytest.mark.asyncio

    async def test_revokes_all_sessions_for_the_tenant(self, client):
        signup_body = signup(client).json()
        # A second session (device) for the same account.
        second_login = client.post(
            "/v1/auth/login",
            json={"email": "dana@example.com", "password": "hunter22"},
        ).json()

        response = client.post(
            "/v1/auth/logout-all-for-tenant",
            headers={"Authorization": f"Bearer {signup_body['access_token']}"},
        )

        assert response.status_code == 200
        assert response.json()["revoked_count"] == 2

        refresh_after = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": second_login["refresh_token"]},
        )
        assert refresh_after.status_code == 401

    async def test_missing_bearer_token_returns_401(self, client):
        response = client.post("/v1/auth/logout-all-for-tenant")

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"

    async def test_garbage_bearer_token_returns_401(self, client):
        response = client.post(
            "/v1/auth/logout-all-for-tenant",
            headers={"Authorization": "Bearer not-a-real-token"},
        )

        assert response.status_code == 401
        assert response.json()["code"] == "invalid_access_token"


class TestFullAccountEntryJourney:
    """Proves the ENTIRE HTTP contract for this API area end to end —
    request in, real JSON response out — not just that individual
    routes work in isolation."""

    def test_signup_then_login_round_trip(self, client):
        signup_response = client.post(
            "/v1/auth/signup",
            json={
                "email": "dana@example.com",
                "password": "hunter22",
                "display_name": "Dana",
                "tenant_label": "Dana's Plumbing",
            },
        )
        assert signup_response.status_code == 201

        login_response = client.post(
            "/v1/auth/login",
            json={"email": "dana@example.com", "password": "hunter22"},
        )
        assert login_response.status_code == 200

        signup_body = signup_response.json()
        login_body = login_response.json()
        assert signup_body["user"]["id"] == login_body["user"]["id"]
        assert signup_body["tenant"]["id"] == login_body["tenant"]["id"]
        # Each call issues its own independent session.
        assert signup_body["refresh_token"] != login_body["refresh_token"]
