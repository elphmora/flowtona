"""tests/unit/repositories/test_email_verification_repository.py"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.repositories.exceptions import ConcurrentUpdateError, RecordNotFoundError

NOW = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_consumption_is_state_guarded(email_verification_repo):
    """mark_consumed() must succeed once and reject a second attempt on
    the same record — the core PENDING-only precondition."""
    verification = await email_verification_repo.create(
        user_id=uuid4(),
        email="dana@example.com",
        token_hash="hash",
        expires_at=NOW + timedelta(hours=24),
    )
    consumed = await email_verification_repo.mark_consumed(
        verification_id=verification.id, consumed_at=NOW
    )
    assert consumed.status.value == "consumed"

    with pytest.raises(ConcurrentUpdateError):
        await email_verification_repo.mark_consumed(
            verification_id=verification.id, consumed_at=NOW
        )


@pytest.mark.asyncio
async def test_resend_revokes_all_prior_pending_records(email_verification_repo):
    user_id = uuid4()
    await email_verification_repo.create(
        user_id=user_id,
        email="dana@example.com",
        token_hash="hash1",
        expires_at=NOW + timedelta(hours=24),
    )
    await email_verification_repo.create(
        user_id=user_id,
        email="dana@example.com",
        token_hash="hash2",
        expires_at=NOW + timedelta(hours=24),
    )
    # unrelated user's pending record must be untouched
    await email_verification_repo.create(
        user_id=uuid4(),
        email="other@example.com",
        token_hash="hash3",
        expires_at=NOW + timedelta(hours=24),
    )

    count = await email_verification_repo.revoke_pending_for_user(
        user_id=user_id, revoked_at=NOW
    )
    assert count == 2

    v1_after = await email_verification_repo.get_by_token_hash(token_hash="hash1")
    v2_after = await email_verification_repo.get_by_token_hash(token_hash="hash2")
    other_after = await email_verification_repo.get_by_token_hash(token_hash="hash3")
    assert v1_after.status.value == "revoked"
    assert v2_after.status.value == "revoked"
    assert other_after.status.value == "pending"


@pytest.mark.asyncio
async def test_consumption_rejects_expired_record(email_verification_repo):
    """Guards the actual fix: mark_consumed() must check expiry, not
    just status — matching InvitationRepository.mark_accepted()."""
    verification = await email_verification_repo.create(
        user_id=uuid4(),
        email="dana@example.com",
        token_hash="hash",
        expires_at=NOW + timedelta(hours=24),
    )
    too_late = NOW + timedelta(hours=25)  # after expires_at

    with pytest.raises(ConcurrentUpdateError):
        await email_verification_repo.mark_consumed(
            verification_id=verification.id, consumed_at=too_late
        )


@pytest.mark.asyncio
async def test_consumption_records_consumed_at(email_verification_repo):
    verification = await email_verification_repo.create(
        user_id=uuid4(),
        email="dana@example.com",
        token_hash="hash",
        expires_at=NOW + timedelta(hours=24),
    )
    consumed = await email_verification_repo.mark_consumed(
        verification_id=verification.id, consumed_at=NOW
    )
    assert consumed.consumed_at == NOW


@pytest.mark.asyncio
async def test_consumption_rejects_revoked_record(email_verification_repo):
    user_id = uuid4()
    verification = await email_verification_repo.create(
        user_id=user_id,
        email="dana@example.com",
        token_hash="hash",
        expires_at=NOW + timedelta(hours=24),
    )
    await email_verification_repo.revoke_pending_for_user(
        user_id=user_id, revoked_at=NOW
    )

    with pytest.raises(ConcurrentUpdateError):
        await email_verification_repo.mark_consumed(
            verification_id=verification.id, consumed_at=NOW
        )


@pytest.mark.asyncio
async def test_consumption_rejects_nonexistent_record(email_verification_repo):
    with pytest.raises(RecordNotFoundError):
        await email_verification_repo.mark_consumed(
            verification_id=uuid4(), consumed_at=NOW
        )