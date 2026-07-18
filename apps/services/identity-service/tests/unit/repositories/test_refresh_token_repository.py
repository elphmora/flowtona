"""tests/unit/repositories/test_refresh_token_repository.py"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.refresh_token import RefreshTokenStatus
from app.repositories.exceptions import (
    ConcurrentUpdateError,
    DuplicateEntryError,
    RecordNotFoundError,
)

NOW = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_create_starts_a_new_family(refresh_token_repo):
    token = await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=uuid4(),
        token_hash="hash1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    assert token.status == RefreshTokenStatus.ACTIVE
    assert token.issued_at == NOW


@pytest.mark.asyncio
async def test_create_rejects_second_active_token_in_same_family(refresh_token_repo):
    """Defensive guard: create() is for a NEW family (login), not for
    continuing one — that's rotate()'s job."""
    family_id = uuid4()
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=family_id,
        token_hash="hash1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    with pytest.raises(ValueError):
        await refresh_token_repo.create(
            user_id=uuid4(),
            tenant_id=uuid4(),
            family_id=family_id,
            token_hash="hash2",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=15),
        )


@pytest.mark.asyncio
async def test_rotate_success_stays_in_same_family(refresh_token_repo):
    user_id, tenant_id, family_id = uuid4(), uuid4(), uuid4()
    original = await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_id,
        family_id=family_id,
        token_hash="original",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    successor = await refresh_token_repo.rotate(
        current_token_hash="original",
        new_token_hash="successor",
        expires_at=NOW + timedelta(minutes=15),
        rotated_at=NOW,
    )

    assert successor.status == RefreshTokenStatus.ACTIVE
    assert successor.family_id == family_id

    original_after = await refresh_token_repo.get_by_token_hash(token_hash="original")
    assert original_after.status == RefreshTokenStatus.ROTATED
    assert original_after.replaced_by_token_id == successor.id
    assert original.id != successor.id


@pytest.mark.asyncio
async def test_rotate_rejects_already_rotated_token(refresh_token_repo):
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=uuid4(),
        token_hash="original",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.rotate(
        current_token_hash="original",
        new_token_hash="successor1",
        expires_at=NOW + timedelta(minutes=15),
        rotated_at=NOW,
    )

    with pytest.raises(ConcurrentUpdateError) as exc_info:
        await refresh_token_repo.rotate(
            current_token_hash="original",
            new_token_hash="successor2",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,
        )
    assert exc_info.value.actual_state == "rotated"


@pytest.mark.asyncio
async def test_rotate_rejects_revoked_token(refresh_token_repo):
    family_id = uuid4()
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=family_id,
        token_hash="original",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.revoke_family(family_id=family_id, revoked_at=NOW)

    with pytest.raises(ConcurrentUpdateError) as exc_info:
        await refresh_token_repo.rotate(
            current_token_hash="original",
            new_token_hash="successor",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,
        )
    assert exc_info.value.actual_state == "revoked"


@pytest.mark.asyncio
async def test_rotate_rejects_expired_token(refresh_token_repo):
    """No sleep needed — constructs an already-expired-but-structurally-
    valid record directly (both issued_at and expires_at in the past
    relative to real time), now that create() accepts issued_at
    explicitly."""
    past_issued = NOW - timedelta(hours=2)
    past_expires = NOW - timedelta(hours=1)
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=uuid4(),
        token_hash="original",
        issued_at=past_issued,
        expires_at=past_expires,
    )

    with pytest.raises(ConcurrentUpdateError) as exc_info:
        await refresh_token_repo.rotate(
            current_token_hash="original",
            new_token_hash="successor",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,  # NOW is already past_expires
        )
    assert exc_info.value.actual_state == "expired"


@pytest.mark.asyncio
async def test_rotate_rejects_nonexistent_token(refresh_token_repo):
    with pytest.raises(RecordNotFoundError):
        await refresh_token_repo.rotate(
            current_token_hash="never-existed",
            new_token_hash="successor",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,
        )


@pytest.mark.asyncio
async def test_rotate_rejects_duplicate_new_token_hash_without_mutating_original(
    refresh_token_repo,
):
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=uuid4(),
        token_hash="original",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=uuid4(),
        token_hash="already-taken",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    with pytest.raises(DuplicateEntryError):
        await refresh_token_repo.rotate(
            current_token_hash="original",
            new_token_hash="already-taken",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,
        )

    # The duplicate check must happen BEFORE any mutation — the original
    # must still be fully active, not partially rotated.
    original_after = await refresh_token_repo.get_by_token_hash(token_hash="original")
    assert original_after.status == RefreshTokenStatus.ACTIVE
    assert original_after.rotated_at is None
    assert original_after.replaced_by_token_id is None


@pytest.mark.asyncio
async def test_no_observable_mutation_when_rotate_fails(refresh_token_repo):
    """When rotate() fails, the current token's state must be completely
    unchanged — no partial mutation, no successor created."""
    family_id = uuid4()
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=family_id,
        token_hash="original",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.revoke_family(family_id=family_id, revoked_at=NOW)

    with pytest.raises(ConcurrentUpdateError):
        await refresh_token_repo.rotate(
            current_token_hash="original",
            new_token_hash="successor",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,
        )

    unchanged = await refresh_token_repo.get_by_token_hash(token_hash="original")
    assert unchanged.status == RefreshTokenStatus.REVOKED
    assert unchanged.replaced_by_token_id is None

    never_created = await refresh_token_repo.get_by_token_hash(token_hash="successor")
    assert never_created is None


@pytest.mark.asyncio
async def test_concurrent_rotation_only_one_wins(refresh_token_repo):
    """The test that actually validates the reason rotate() was made a
    single atomic operation: two concurrent rotate() calls against the
    SAME active token — exactly one must succeed, the other must fail
    with actual_state == 'rotated', and the original must end up
    pointing at whichever one actually won."""
    await refresh_token_repo.create(
        user_id=uuid4(),
        tenant_id=uuid4(),
        family_id=uuid4(),
        token_hash="original",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    results = await asyncio.gather(
        refresh_token_repo.rotate(
            current_token_hash="original",
            new_token_hash="successor-a",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,
        ),
        refresh_token_repo.rotate(
            current_token_hash="original",
            new_token_hash="successor-b",
            expires_at=NOW + timedelta(minutes=15),
            rotated_at=NOW,
        ),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ConcurrentUpdateError)
    assert failures[0].actual_state == "rotated"

    winner = successes[0]
    original_after = await refresh_token_repo.get_by_token_hash(token_hash="original")
    assert original_after.replaced_by_token_id == winner.id

    # Only one successor was actually created — the loser's token_hash
    # never made it into the store.
    loser_hash = "successor-b" if winner.token_hash == "successor-a" else "successor-a"
    assert await refresh_token_repo.get_by_token_hash(token_hash=loser_hash) is None


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
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.rotate(
        current_token_hash="hashA",
        new_token_hash="hashB",
        expires_at=NOW + timedelta(minutes=15),
        rotated_at=NOW,
    )

    count = await refresh_token_repo.revoke_family(family_id=family_id, revoked_at=NOW)
    assert count == 2  # both the rotated ancestor AND the active leaf

    a_after = await refresh_token_repo.get_by_token_hash(token_hash="hashA")
    b_after = await refresh_token_repo.get_by_token_hash(token_hash="hashB")
    assert a_after.status == RefreshTokenStatus.REVOKED
    assert b_after.status == RefreshTokenStatus.REVOKED


@pytest.mark.asyncio
async def test_revoke_all_for_tenant_covers_all_families_but_not_another_tenant(
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
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_a,
        family_id=family_2,
        token_hash="device2",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    await refresh_token_repo.create(
        user_id=user_id,
        tenant_id=tenant_b,
        family_id=family_3,
        token_hash="device3-other-tenant",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )

    count = await refresh_token_repo.revoke_all_for_tenant(
        user_id=user_id, tenant_id=tenant_a, revoked_at=NOW
    )
    assert count == 2

    device1 = await refresh_token_repo.get_by_token_hash(token_hash="device1")
    device2 = await refresh_token_repo.get_by_token_hash(token_hash="device2")
    device3 = await refresh_token_repo.get_by_token_hash(
        token_hash="device3-other-tenant"
    )
    assert device1.status == RefreshTokenStatus.REVOKED
    assert device2.status == RefreshTokenStatus.REVOKED
    assert device3.status == RefreshTokenStatus.ACTIVE  # other tenant, untouched
