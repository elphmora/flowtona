"""tests/unit/repositories/test_refresh_token_repository.py"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.repositories.exceptions import ConcurrentUpdateError

NOW = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_token_cannot_rotate_twice(refresh_token_repo):
    user_id, tenant_id, family_id = uuid4(), uuid4(), uuid4()
    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_id,
        family_id=family_id,
        token_hash="hash1",
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.mark_rotated(
        token_hash="hash1", replaced_by_token_id=uuid4(), rotated_at=NOW
    )

    with pytest.raises(ConcurrentUpdateError):
        await refresh_token_repo.mark_rotated(
            token_hash="hash1", replaced_by_token_id=uuid4(), rotated_at=NOW
        )


@pytest.mark.asyncio
async def test_family_revocation_includes_rotated_ancestors(refresh_token_repo):
    """A -> rotated -> B -> active. revoke_family() must revoke BOTH,
    not just the current active leaf."""
    user_id, tenant_id, family_id = uuid4(), uuid4(), uuid4()
    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_id,
        family_id=family_id,
        token_hash="hashA",
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.mark_rotated(
        token_hash="hashA", replaced_by_token_id=uuid4(), rotated_at=NOW
    )
    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_id,
        family_id=family_id,
        token_hash="hashB",
        expires_at=NOW + timedelta(minutes=15),
    )

    count = await refresh_token_repo.revoke_family(family_id=family_id, revoked_at=NOW)
    assert count == 2  # both the rotated ancestor AND the active leaf

    a_after = await refresh_token_repo.get_by_token_hash(token_hash="hashA")
    b_after = await refresh_token_repo.get_by_token_hash(token_hash="hashB")
    assert a_after.status.value == "revoked"
    assert b_after.status.value == "revoked"


@pytest.mark.asyncio
async def test_logout_all_covers_all_families_but_not_another_tenant(
    refresh_token_repo,
):
    """Two families for (user, tenant_A) — logout-all on tenant_A must
    revoke both, but leave a family under tenant_B (same user) untouched."""
    user_id, tenant_a, tenant_b = uuid4(), uuid4(), uuid4()
    family_1, family_2, family_3 = uuid4(), uuid4(), uuid4()

    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_a,
        family_id=family_1,
        token_hash="device1",
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_a,
        family_id=family_2,
        token_hash="device2",
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_b,
        family_id=family_3,
        token_hash="device3-other-tenant",
        expires_at=NOW + timedelta(minutes=15),
    )

    count = await refresh_token_repo.revoke_all_active(
        user_id=user_id, tenant_id=tenant_a, revoked_at=NOW
    )
    assert count == 2

    device1 = await refresh_token_repo.get_by_token_hash(token_hash="device1")
    device2 = await refresh_token_repo.get_by_token_hash(token_hash="device2")
    device3 = await refresh_token_repo.get_by_token_hash(
        token_hash="device3-other-tenant"
    )
    assert device1.status.value == "revoked"
    assert device2.status.value == "revoked"
    assert device3.status.value == "active"  # other tenant, untouched
