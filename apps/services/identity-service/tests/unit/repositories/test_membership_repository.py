"""tests/unit/repositories/test_membership_repository.py"""

from uuid import uuid4

import pytest

from app.constants.roles import Role
from app.repositories.exceptions import DuplicateEntryError


@pytest.mark.asyncio
async def test_duplicate_membership_rejected(membership_repo):
    user_id, tenant_id = uuid4(), uuid4()
    await membership_repo.create(user_id=user_id, tenant_id=tenant_id, role=Role.OWNER)

    with pytest.raises(DuplicateEntryError):
        await membership_repo.create(
            user_id=user_id, tenant_id=tenant_id, role=Role.TECHNICIAN
        )


@pytest.mark.asyncio
async def test_membership_listing_preserves_insertion_order(membership_repo):
    user_id = uuid4()
    tenant_a, tenant_b, tenant_c = uuid4(), uuid4(), uuid4()

    m1 = await membership_repo.create(
        user_id=user_id, tenant_id=tenant_a, role=Role.OWNER
    )
    m2 = await membership_repo.create(
        user_id=user_id, tenant_id=tenant_b, role=Role.TECHNICIAN
    )
    m3 = await membership_repo.create(
        user_id=user_id, tenant_id=tenant_c, role=Role.DISPATCHER
    )

    memberships = await membership_repo.get_memberships_for_user(user_id=user_id)
    assert [m.id for m in memberships] == [m1.id, m2.id, m3.id]


@pytest.mark.asyncio
async def test_returned_models_are_copies(membership_repo):
    user_id, tenant_id = uuid4(), uuid4()
    membership = await membership_repo.create(
        user_id=user_id, tenant_id=tenant_id, role=Role.OWNER
    )
    membership.role = Role.TECHNICIAN  # mutate the returned object directly

    fetched = await membership_repo.get_by_user_and_tenant(
        user_id=user_id, tenant_id=tenant_id
    )
    assert fetched.role == Role.OWNER  # unaffected


@pytest.mark.asyncio
async def test_update_rejects_identity_field_change(membership_repo):
    user_id, tenant_id = uuid4(), uuid4()
    membership = await membership_repo.create(
        user_id=user_id, tenant_id=tenant_id, role=Role.OWNER
    )
    membership.tenant_id = uuid4()  # attempt to change identity field

    with pytest.raises(NotImplementedError):
        await membership_repo.update(membership=membership)


@pytest.mark.asyncio
async def test_bump_permissions_version_for_user_increments_every_membership(
    membership_repo,
):
    user_id = uuid4()
    m1 = await membership_repo.create(
        user_id=user_id, tenant_id=uuid4(), role=Role.OWNER
    )
    m2 = await membership_repo.create(
        user_id=user_id, tenant_id=uuid4(), role=Role.TECHNICIAN
    )

    updated = await membership_repo.bump_permissions_version_for_user(user_id=user_id)

    assert len(updated) == 2
    assert {m.id for m in updated} == {m1.id, m2.id}
    assert all(m.permissions_version == 1 for m in updated)

    # Confirm persisted, independent of the returned objects.
    persisted_1 = await membership_repo.get_by_user_and_tenant(
        user_id=user_id, tenant_id=m1.tenant_id
    )
    persisted_2 = await membership_repo.get_by_user_and_tenant(
        user_id=user_id, tenant_id=m2.tenant_id
    )
    assert persisted_1.permissions_version == 1
    assert persisted_2.permissions_version == 1


@pytest.mark.asyncio
async def test_bump_permissions_version_for_user_does_not_affect_other_users(
    membership_repo,
):
    user_a, user_b = uuid4(), uuid4()
    await membership_repo.create(user_id=user_a, tenant_id=uuid4(), role=Role.OWNER)
    membership_b = await membership_repo.create(
        user_id=user_b, tenant_id=uuid4(), role=Role.OWNER
    )

    await membership_repo.bump_permissions_version_for_user(user_id=user_a)

    unaffected = await membership_repo.get_by_user_and_tenant(
        user_id=user_b, tenant_id=membership_b.tenant_id
    )
    assert unaffected.permissions_version == 0


@pytest.mark.asyncio
async def test_bump_permissions_version_for_user_returns_empty_list_when_no_memberships(
    membership_repo,
):
    result = await membership_repo.bump_permissions_version_for_user(user_id=uuid4())
    assert result == []
