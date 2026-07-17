"""tests/unit/services/test_membership_service.py"""

from uuid import uuid4

import pytest

from app.constants.roles import Role
from app.exceptions.membership import AlreadyAMemberError
from app.services.membership_service import MembershipService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service(membership_repo) -> MembershipService:
    return MembershipService(membership_repo)


class TestCreate:
    async def test_creates_membership(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        membership = await service.create(
            user_id=user_id, tenant_id=tenant_id, role=Role.OWNER
        )
        assert membership.user_id == user_id
        assert membership.tenant_id == tenant_id
        assert membership.role == Role.OWNER

    async def test_duplicate_membership_raises_domain_exception(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        await service.create(user_id=user_id, tenant_id=tenant_id, role=Role.OWNER)

        with pytest.raises(AlreadyAMemberError):
            await service.create(
                user_id=user_id, tenant_id=tenant_id, role=Role.TECHNICIAN
            )

    async def test_duplicate_creation_does_not_overwrite_existing_role(self, service):
        """The uniqueness check must happen BEFORE any write — a failed
        duplicate create() attempt must leave the original membership's
        role untouched, not silently overwritten by the rejected
        attempt's role."""
        user_id, tenant_id = uuid4(), uuid4()
        await service.create(user_id=user_id, tenant_id=tenant_id, role=Role.OWNER)

        with pytest.raises(AlreadyAMemberError):
            await service.create(
                user_id=user_id, tenant_id=tenant_id, role=Role.TECHNICIAN
            )

        existing = await service.get_by_user_and_tenant(
            user_id=user_id, tenant_id=tenant_id
        )
        assert existing is not None
        assert existing.role == Role.OWNER


class TestLookups:
    async def test_get_by_user_and_tenant_roundtrip(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        created = await service.create(
            user_id=user_id, tenant_id=tenant_id, role=Role.OWNER
        )
        fetched = await service.get_by_user_and_tenant(
            user_id=user_id, tenant_id=tenant_id
        )
        assert fetched.id == created.id

    async def test_get_by_user_and_tenant_returns_none_when_absent(self, service):
        result = await service.get_by_user_and_tenant(
            user_id=uuid4(), tenant_id=uuid4()
        )
        assert result is None

    async def test_get_memberships_for_user_preserves_order(self, service):
        user_id = uuid4()
        m1 = await service.create(user_id=user_id, tenant_id=uuid4(), role=Role.OWNER)
        m2 = await service.create(
            user_id=user_id, tenant_id=uuid4(), role=Role.TECHNICIAN
        )
        memberships = await service.get_memberships_for_user(user_id=user_id)
        assert [m.id for m in memberships] == [m1.id, m2.id]


class TestBumpPermissionsVersionForUser:
    async def test_increments_version_on_every_membership(self, service):
        user_id = uuid4()
        m1 = await service.create(user_id=user_id, tenant_id=uuid4(), role=Role.OWNER)
        m2 = await service.create(
            user_id=user_id, tenant_id=uuid4(), role=Role.TECHNICIAN
        )
        assert m1.permissions_version == 0
        assert m2.permissions_version == 0

        updated = await service.bump_permissions_version_for_user(user_id=user_id)

        assert len(updated) == 2
        assert all(m.permissions_version == 1 for m in updated)

        # Confirm the bump was actually persisted, not just returned —
        # reload independently rather than trusting the return value.
        persisted_1 = await service.get_by_user_and_tenant(
            user_id=user_id, tenant_id=m1.tenant_id
        )
        persisted_2 = await service.get_by_user_and_tenant(
            user_id=user_id, tenant_id=m2.tenant_id
        )
        assert persisted_1 is not None
        assert persisted_2 is not None
        assert persisted_1.permissions_version == 1
        assert persisted_2.permissions_version == 1

    async def test_second_bump_increments_again(self, service):
        user_id = uuid4()
        await service.create(user_id=user_id, tenant_id=uuid4(), role=Role.OWNER)

        await service.bump_permissions_version_for_user(user_id=user_id)
        second = await service.bump_permissions_version_for_user(user_id=user_id)

        assert second[0].permissions_version == 2

    async def test_does_not_affect_other_users_memberships(self, service):
        user_a, user_b = uuid4(), uuid4()
        await service.create(user_id=user_a, tenant_id=uuid4(), role=Role.OWNER)
        membership_b = await service.create(
            user_id=user_b, tenant_id=uuid4(), role=Role.OWNER
        )

        await service.bump_permissions_version_for_user(user_id=user_a)

        unaffected = await service.get_by_user_and_tenant(
            user_id=user_b, tenant_id=membership_b.tenant_id
        )
        assert unaffected.permissions_version == 0

    async def test_returns_empty_list_for_user_with_no_memberships(self, service):
        result = await service.bump_permissions_version_for_user(user_id=uuid4())
        assert result == []
