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
