"""tests/unit/services/test_auth_models.py

This file verifies exactly one thing: frozen + slotted dataclass
behavior. Deliberately constructs domain models DIRECTLY, not through
the service layer — going through UserService/TenantService/etc.
would couple a test about dataclass immutability to hashing,
validation, repository plumbing, and whatever those services evolve
to require, for zero benefit to what's actually being tested here.
The models below are intentionally simple (flat Pydantic models, no
business logic to exercise), so direct construction is the right
scope match.

Frozen and slotted are tested SEPARATELY, not with one assignment
attempt covering both — a frozen dataclass's generated __setattr__
intercepts ANY assignment, declared attribute or not, so attempting to
set an undeclared attribute on a frozen+slotted instance raises
FrozenInstanceError before slots ever come into play. That would just
re-prove frozen-ness under a different test name. The actual way to
confirm slots removed __dict__ is checking for its absence directly.
"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.constants.roles import Role
from app.models.invitation import Invitation, InvitationStatus
from app.models.membership import TenantMembership
from app.models.tenant import Tenant
from app.models.user import User
from app.services.auth_models import (
    AuthenticatedSession,
    InviteAcceptanceResult,
    TenantSelectionRequired,
)


def _make_user() -> User:
    return User(
        email="dana@example.com",
        password_hash="x",
        display_name="Dana",
        email_verified=False,
        created_at=datetime.now(timezone.utc),
    )


def _make_tenant() -> Tenant:
    return Tenant(tenant_label="Dana's Plumbing", created_at=datetime.now(timezone.utc))


def _make_membership(user_id: UUID, tenant_id: UUID) -> TenantMembership:
    return TenantMembership(
        user_id=user_id,
        tenant_id=tenant_id,
        role=Role.OWNER,
        created_at=datetime.now(timezone.utc),
    )


def _make_invitation(tenant_id: UUID) -> Invitation:
    now = datetime.now(timezone.utc)
    return Invitation(
        tenant_id=tenant_id,
        email="new@example.com",
        role=Role.TECHNICIAN,
        token_hash="hash",
        invited_by_user_id=uuid4(),
        created_at=now,
        expires_at=now + timedelta(days=7),
        status=InvitationStatus.PENDING,
    )


class TestAuthenticatedSession:
    def test_is_frozen(self):
        user = _make_user()
        tenant = _make_tenant()
        session = AuthenticatedSession(
            user=user,
            tenant=tenant,
            membership=_make_membership(user.id, tenant.id),
            access_token="access",
            raw_refresh_token="refresh",
        )
        with pytest.raises(FrozenInstanceError):
            session.access_token = "different"  # type: ignore[misc]

    def test_is_slotted(self):
        user = _make_user()
        tenant = _make_tenant()
        session = AuthenticatedSession(
            user=user,
            tenant=tenant,
            membership=_make_membership(user.id, tenant.id),
            access_token="access",
            raw_refresh_token="refresh",
        )
        assert not hasattr(session, "__dict__")


class TestTenantSelectionRequired:
    def test_is_frozen(self):
        user = _make_user()
        result = TenantSelectionRequired(user=user, preauth_token="preauth")
        with pytest.raises(FrozenInstanceError):
            result.preauth_token = "different"  # type: ignore[misc]

    def test_is_slotted(self):
        user = _make_user()
        result = TenantSelectionRequired(user=user, preauth_token="preauth")
        assert not hasattr(result, "__dict__")


class TestInviteAcceptanceResult:
    def test_is_frozen(self):
        tenant = _make_tenant()
        invitee_user_id = uuid4()
        result = InviteAcceptanceResult(
            invitation=_make_invitation(tenant.id),
            tenant=tenant,
            membership=_make_membership(invitee_user_id, tenant.id),
        )
        with pytest.raises(FrozenInstanceError):
            result.tenant = tenant  # type: ignore[misc]

    def test_is_slotted(self):
        tenant = _make_tenant()
        invitee_user_id = uuid4()
        result = InviteAcceptanceResult(
            invitation=_make_invitation(tenant.id),
            tenant=tenant,
            membership=_make_membership(invitee_user_id, tenant.id),
        )
        assert not hasattr(result, "__dict__")
