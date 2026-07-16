"""tests/unit/services/test_permission_service.py"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.constants.permissions import Permission
from app.constants.roles import Role
from app.models.membership import MembershipStatus, TenantMembership
from app.models.user import User
from app.services.permission_service import PermissionService

NOW = datetime.now(timezone.utc)


def make_user(*, email_verified: bool) -> User:
    return User(
        email="dana@example.com",
        password_hash="hash",
        display_name="Dana",
        email_verified=email_verified,
        created_at=NOW,
    )


def make_membership(
    *, user_id, role: Role, status: MembershipStatus = MembershipStatus.ACTIVE
) -> TenantMembership:
    return TenantMembership(
        user_id=user_id,
        tenant_id=uuid4(),
        role=role,
        status=status,
        created_at=NOW,
    )


@pytest.fixture
def service() -> PermissionService:
    return PermissionService()


def test_verified_owner_gets_full_role_permissions(service):
    user = make_user(email_verified=True)
    membership = make_membership(user_id=user.id, role=Role.OWNER)

    perms = service.effective_permissions(user=user, membership=membership)

    assert perms == frozenset(
        {Permission.BILLING_MANAGE, Permission.SCHEDULE_READ, Permission.MEMBERS_INVITE}
    )


def test_unverified_owner_loses_soft_gated_permissions_but_keeps_schedule_read(service):
    user = make_user(email_verified=False)
    membership = make_membership(user_id=user.id, role=Role.OWNER)

    perms = service.effective_permissions(user=user, membership=membership)

    assert perms == frozenset({Permission.SCHEDULE_READ})
    assert Permission.BILLING_MANAGE not in perms
    assert Permission.MEMBERS_INVITE not in perms


def test_unverified_technician_is_unaffected_by_soft_gate(service):
    """Technician's role permissions are already just SCHEDULE_READ —
    the soft gate has nothing to remove, so verified vs. unverified
    should be identical for this role."""
    user_verified = make_user(email_verified=True)
    user_unverified = make_user(email_verified=False)
    membership_verified = make_membership(
        user_id=user_verified.id, role=Role.TECHNICIAN
    )
    membership_unverified = make_membership(
        user_id=user_unverified.id, role=Role.TECHNICIAN
    )

    assert service.effective_permissions(
        user=user_verified, membership=membership_verified
    ) == service.effective_permissions(
        user=user_unverified, membership=membership_unverified
    )


@pytest.mark.parametrize(
    "status", [MembershipStatus.SUSPENDED, MembershipStatus.REVOKED]
)
def test_inactive_membership_has_no_permissions_regardless_of_role_or_verification(
    service, status
):
    user = make_user(email_verified=True)
    membership = make_membership(user_id=user.id, role=Role.OWNER, status=status)

    perms = service.effective_permissions(user=user, membership=membership)

    assert perms == frozenset()


def test_mismatched_user_and_membership_raises(service):
    user = make_user(email_verified=True)
    membership = make_membership(user_id=uuid4(), role=Role.OWNER)  # different user_id

    with pytest.raises(ValueError):
        service.effective_permissions(user=user, membership=membership)


def test_has_permission_true_case(service):
    user = make_user(email_verified=True)
    membership = make_membership(user_id=user.id, role=Role.OWNER)

    assert service.has_permission(
        user=user, membership=membership, permission=Permission.BILLING_MANAGE
    )


def test_has_permission_false_case_due_to_soft_gate(service):
    user = make_user(email_verified=False)
    membership = make_membership(user_id=user.id, role=Role.OWNER)

    assert not service.has_permission(
        user=user, membership=membership, permission=Permission.BILLING_MANAGE
    )
