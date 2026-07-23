"""tests/unit/api/test_invite_routes.py

End-to-end HTTP tests for invitation creation and acceptance.
"""

from uuid import UUID

import pytest

from app.constants.roles import Role


def signup(client, *, email="dana@example.com", tenant_label="Dana's Plumbing"):
    return client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": "hunter22",
            "display_name": "Dana",
            "tenant_label": tenant_label,
        },
    )


async def create_verified_owner_session(client, registry):
    """members:invite is soft-gated on email verification — a freshly
    signed-up owner isn't verified yet, so tests need to verify first
    or every create_invite call would fail on the soft gate rather
    than exercising the actual behavior being tested."""
    signup_body = signup(client).json()
    user_id = UUID(signup_body["user"]["id"])
    raw_token = await registry.email_verification_service.resend(
        user_id=user_id, email="dana@example.com"
    )
    client.post("/v1/auth/verify-email", json={"token": raw_token})
    return signup_body


async def create_pending_invite(client, registry, *, email="invitee@example.com"):
    """Sets up an owner + a pending invitation via registry directly,
    not the real HTTP create route — this module's acceptance test
    classes are testing acceptance, creation is TestCreateInvite's job."""
    owner_body = await create_verified_owner_session(client, registry)
    invitation, raw_token = await registry.invitation_service.create(
        tenant_id=UUID(owner_body["tenant"]["id"]),
        email=email,
        role=Role.DISPATCHER,
        invited_by_user_id=UUID(owner_body["user"]["id"]),
    )
    return owner_body, invitation, raw_token


class TestCreateInvite:
    pytestmark = pytest.mark.asyncio

    async def test_returns_201(self, client, registry):
        signup_body = await create_verified_owner_session(client, registry)

        response = client.post(
            f"/v1/tenants/{signup_body['tenant']['id']}/invitations",
            json={"email": "new.tech@example.com", "role": "technician"},
            headers={"Authorization": f"Bearer {signup_body['access_token']}"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "new.tech@example.com"
        assert body["role"] == "technician"
        assert body["status"] == "pending"

    async def test_mismatched_tenant_id_returns_403(self, client, registry):
        """The route-level scope check: the URL's tenant_id must match
        the caller's OWN authenticated tenant (claims.tenant_id), not
        just any tenant they happen to belong to."""
        signup_body = await create_verified_owner_session(client, registry)
        other_tenant = await registry.tenant_service.create(
            tenant_label="A Different Business"
        )

        response = client.post(
            f"/v1/tenants/{other_tenant.id}/invitations",
            json={"email": "new.tech@example.com", "role": "technician"},
            headers={"Authorization": f"Bearer {signup_body['access_token']}"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    async def test_technician_cannot_invite(self, client, registry):
        """A technician lacks members:invite regardless of verification
        status — this is a role check, not the soft gate.

        Creates the technician user directly via user_service, not
        signup() — signup() would ALSO create a brand-new tenant,
        making this user an owner there too. With two active
        memberships, login() would correctly return
        TenantSelectionRequired instead of a session, which isn't what
        this test is trying to exercise at all."""
        owner_body = await create_verified_owner_session(client, registry)
        tech_user = await registry.user_service.create(
            email="tech@example.com", password="hunter22", display_name="Tech"
        )
        await registry.membership_service.create(
            user_id=tech_user.id,
            tenant_id=UUID(owner_body["tenant"]["id"]),
            role=Role.TECHNICIAN,
        )
        tech_login = client.post(
            "/v1/auth/login",
            json={"email": "tech@example.com", "password": "hunter22"},
        ).json()

        response = client.post(
            f"/v1/tenants/{owner_body['tenant']['id']}/invitations",
            json={"email": "someone@example.com", "role": "technician"},
            headers={"Authorization": f"Bearer {tech_login['access_token']}"},
        )

        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"

    async def test_missing_bearer_token_returns_401(self, client, registry):
        signup_body = await create_verified_owner_session(client, registry)

        response = client.post(
            f"/v1/tenants/{signup_body['tenant']['id']}/invitations",
            json={"email": "new.tech@example.com", "role": "technician"},
        )

        assert response.status_code == 401


class TestAcceptInviteExistingUser:
    pytestmark = pytest.mark.asyncio

    async def test_returns_201_without_minting_a_session(self, client, registry):
        owner_body, _invitation, raw_token = await create_pending_invite(
            client, registry
        )
        invitee_body = signup(
            client, email="invitee@example.com", tenant_label="Invitee's Own Business"
        ).json()

        response = client.post(
            "/v1/invitations/accept-existing-user",
            json={"token": raw_token},
            headers={"Authorization": f"Bearer {invitee_body['access_token']}"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["membership"]["role"] == "dispatcher"
        assert body["tenant"]["id"] == owner_body["tenant"]["id"]

        # No new session minted — the invitee's OWN original session
        # must still work, and their active tenant must be unchanged.
        refreshed = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": invitee_body["refresh_token"]},
        ).json()
        assert refreshed["tenant"]["id"] == invitee_body["tenant"]["id"]

    async def test_email_mismatch_returns_409(self, client, registry):
        _owner_body, _invitation, raw_token = await create_pending_invite(
            client, registry
        )
        someone_else_body = signup(
            client, email="someone.else@example.com", tenant_label="Different Business"
        ).json()

        response = client.post(
            "/v1/invitations/accept-existing-user",
            json={"token": raw_token},
            headers={"Authorization": f"Bearer {someone_else_body['access_token']}"},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "invitation_email_mismatch"

    async def test_invalid_token_returns_400(self, client, registry):
        owner_body = await create_verified_owner_session(client, registry)

        response = client.post(
            "/v1/invitations/accept-existing-user",
            json={"token": "not-a-real-token"},
            headers={"Authorization": f"Bearer {owner_body['access_token']}"},
        )

        assert response.status_code == 400
        assert response.json()["code"] == "invalid_invitation"

    async def test_missing_bearer_token_returns_401(self, client, registry):
        _owner_body, _invitation, raw_token = await create_pending_invite(
            client, registry
        )

        response = client.post(
            "/v1/invitations/accept-existing-user", json={"token": raw_token}
        )

        assert response.status_code == 401


class TestAcceptInviteNewUser:
    pytestmark = pytest.mark.asyncio

    async def test_returns_201_with_verified_user(self, client, registry):
        owner_body = await create_verified_owner_session(client, registry)
        _invitation, raw_token = await registry.invitation_service.create(
            tenant_id=UUID(owner_body["tenant"]["id"]),
            email="new.invitee@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=UUID(owner_body["user"]["id"]),
        )

        response = client.post(
            "/v1/invitations/accept-new-user",
            json={
                "token": raw_token,
                "password": "hunter22",
                "display_name": "Invitee",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["user"]["email"] == "new.invitee@example.com"
        assert body["user"]["email_verified"] is True  # Invariant 9
        assert body["membership"]["role"] == "technician"
        assert body["access_token"]
        assert body["refresh_token"]

    async def test_invalid_token_returns_400(self, client):
        response = client.post(
            "/v1/invitations/accept-new-user",
            json={
                "token": "not-a-real-token",
                "password": "hunter22",
                "display_name": "Invitee",
            },
        )

        assert response.status_code == 400
        assert response.json()["code"] == "invalid_invitation"

    async def test_duplicate_email_returns_409(self, client, registry):
        owner_body = await create_verified_owner_session(client, registry)
        signup(client, email="already.exists@example.com")
        _invitation, raw_token = await registry.invitation_service.create(
            tenant_id=UUID(owner_body["tenant"]["id"]),
            email="already.exists@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=UUID(owner_body["user"]["id"]),
        )

        response = client.post(
            "/v1/invitations/accept-new-user",
            json={
                "token": raw_token,
                "password": "hunter22",
                "display_name": "Dupe",
            },
        )

        assert response.status_code == 409
        assert response.json()["code"] == "email_already_registered"
