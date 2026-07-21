"""tests/unit/api/test_mappers.py

Tests for app/api/mappers.py — the domain-object -> HTTP-response
conversion. The single most important property tested here: User's
password_hash must never appear anywhere in the mapped output, under
any circumstance.
"""

from datetime import datetime, timezone

from app.api.mappers import (
    to_authenticated_session_response,
    to_tenant_selection_required_response,
)
from app.api.schemas.auth import (
    AuthenticatedSessionResponse,
    TenantSelectionRequiredResponse,
)
from app.constants.roles import Role
from app.models.membership import TenantMembership
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_models import AuthenticatedSession, TenantSelectionRequired

_NOW = datetime.now(timezone.utc)


def _make_user(password_hash: str = "$argon2id$super-secret-hash") -> User:
    return User(
        email="dana@example.com",
        password_hash=password_hash,
        display_name="Dana",
        email_verified=True,
        created_at=_NOW,
    )


def _make_tenant() -> Tenant:
    return Tenant(tenant_label="Dana's Plumbing", created_at=_NOW)


def _make_membership(user_id, tenant_id) -> TenantMembership:
    return TenantMembership(
        user_id=user_id, tenant_id=tenant_id, role=Role.OWNER, created_at=_NOW
    )


class TestAuthenticatedSessionMapping:
    def test_produces_correct_response_shape(self):
        user = _make_user()
        tenant = _make_tenant()
        session = AuthenticatedSession(
            user=user,
            tenant=tenant,
            membership=_make_membership(user.id, tenant.id),
            access_token="the-access-token",
            raw_refresh_token="the-raw-refresh-token",
        )

        response = to_authenticated_session_response(session)

        assert isinstance(response, AuthenticatedSessionResponse)
        assert response.result == "authenticated"
        assert response.access_token == "the-access-token"
        assert response.refresh_token == "the-raw-refresh-token"

    def test_exact_response_payload(self):
        """Stronger than a substring check — an EXACT expected payload
        catches accidental future additions a "password_hash not in
        the output" test alone wouldn't. If someone later adds a new
        User field (e.g. failed_login_attempts) and forgets to update
        UserResponse/to_user_response deliberately, this test fails
        immediately rather than silently passing."""
        user = _make_user(password_hash="UNMISTAKABLE_SECRET_MARKER_VALUE")
        tenant = _make_tenant()
        membership = _make_membership(user.id, tenant.id)
        session = AuthenticatedSession(
            user=user,
            tenant=tenant,
            membership=membership,
            access_token="access",
            raw_refresh_token="refresh",
        )

        response = to_authenticated_session_response(session)

        assert response.model_dump() == {
            "result": "authenticated",
            "user": {
                "id": user.id,
                "email": "dana@example.com",
                "display_name": "Dana",
                "email_verified": True,
            },
            "tenant": {"id": tenant.id, "tenant_label": "Dana's Plumbing"},
            "membership": {
                "role": membership.role,
                "permissions_version": membership.permissions_version,
            },
            "access_token": "access",
            "refresh_token": "refresh",
        }
        assert "UNMISTAKABLE_SECRET_MARKER_VALUE" not in response.model_dump_json()


def _make_authenticated_response() -> AuthenticatedSessionResponse:
    user = _make_user()
    tenant = _make_tenant()
    session = AuthenticatedSession(
        user=user,
        tenant=tenant,
        membership=_make_membership(user.id, tenant.id),
        access_token="access",
        raw_refresh_token="refresh",
    )
    return to_authenticated_session_response(session)


class TestResponseFieldCompleteness:
    """Cheap insurance distinct from the exact-payload tests above —
    those catch accidental additions to the OUTER response shapes
    (AuthenticatedSessionResponse, etc.); these catch accidental
    expansion of the shared building blocks themselves (UserResponse,
    TenantResponse, MembershipResponse), which every outer response
    reuses."""

    def test_user_response_has_only_expected_fields(self):
        response = _make_authenticated_response()

        assert set(response.user.model_dump().keys()) == {
            "id",
            "email",
            "display_name",
            "email_verified",
        }

    def test_tenant_response_has_only_expected_fields(self):
        response = _make_authenticated_response()

        assert set(response.tenant.model_dump().keys()) == {"id", "tenant_label"}

    def test_membership_response_has_only_expected_fields(self):
        response = _make_authenticated_response()

        assert set(response.membership.model_dump().keys()) == {
            "role",
            "permissions_version",
        }


class TestTenantSelectionRequiredMapping:
    def test_produces_correct_response_shape(self):
        user = _make_user()
        result = TenantSelectionRequired(user=user, preauth_token="preauth")

        response = to_tenant_selection_required_response(result)

        assert isinstance(response, TenantSelectionRequiredResponse)
        assert response.result == "tenant_selection_required"
        assert response.preauth_token == "preauth"

    def test_exact_response_payload(self):
        user = _make_user(password_hash="UNMISTAKABLE_SECRET_MARKER_VALUE")
        result = TenantSelectionRequired(user=user, preauth_token="preauth")

        response = to_tenant_selection_required_response(result)

        assert response.model_dump() == {
            "result": "tenant_selection_required",
            "user": {
                "id": user.id,
                "email": "dana@example.com",
                "display_name": "Dana",
                "email_verified": True,
            },
            "preauth_token": "preauth",
        }
        assert "UNMISTAKABLE_SECRET_MARKER_VALUE" not in response.model_dump_json()
