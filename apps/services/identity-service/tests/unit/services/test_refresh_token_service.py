"""tests/unit/services/test_refresh_token_service.py"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.exceptions.refresh_token import (
    InvalidRefreshTokenError,
    RefreshTokenReuseDetectedError,
)
from app.security.hashing import hash_token
from app.services.refresh_token_service import RefreshTokenService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service(refresh_token_repo) -> RefreshTokenService:
    return RefreshTokenService(refresh_token_repo)


class TestIssue:
    async def test_issues_active_token_with_new_family(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        record, raw_token = await service.issue(user_id=user_id, tenant_id=tenant_id)
        assert record.status.value == "active"
        assert record.user_id == user_id
        assert record.tenant_id == tenant_id
        assert isinstance(raw_token, str) and len(raw_token) > 0

    async def test_two_issues_get_different_families(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        record1, _ = await service.issue(user_id=user_id, tenant_id=tenant_id)
        record2, _ = await service.issue(user_id=user_id, tenant_id=tenant_id)
        assert record1.family_id != record2.family_id


class TestRotate:
    async def test_successful_rotation_stays_in_same_family(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        original, raw_token = await service.issue(user_id=user_id, tenant_id=tenant_id)

        successor, new_raw_token = await service.rotate(raw_token=raw_token)

        assert successor.family_id == original.family_id
        assert successor.status.value == "active"
        assert new_raw_token != raw_token

    async def test_unknown_token_raises_invalid(self, service):
        with pytest.raises(InvalidRefreshTokenError):
            await service.rotate(raw_token="never-issued")

    async def test_reuse_of_rotated_token_raises_reuse_and_revokes_family(
        self, service
    ):
        user_id, tenant_id = uuid4(), uuid4()
        _, raw_token = await service.issue(user_id=user_id, tenant_id=tenant_id)
        _, new_raw_token = await service.rotate(raw_token=raw_token)

        # Reuse the OLD (already-rotated) token — the actual theft scenario.
        with pytest.raises(RefreshTokenReuseDetectedError):
            await service.rotate(raw_token=raw_token)

        # The whole family, including the legitimate current token, is
        # now revoked — the intended tradeoff (Decision 11).
        with pytest.raises(InvalidRefreshTokenError):
            await service.rotate(raw_token=new_raw_token)

    async def test_lost_race_revokes_even_the_legitimate_winning_successor(
        self, service, refresh_token_repo
    ):
        """Deterministic simulation of the race, not real concurrency —
        demonstrates the actual security OUTCOME (Decision 11's
        deliberate tradeoff), not just that an exception type is raised.
        A second request wins the rotation race first (simulated by
        calling the repository directly); when the stale-token holder's
        request then arrives via the service, it must detect reuse AND
        the family-wide revocation must catch the legitimate winner's
        successor too — not just reject the loser."""
        user_id, tenant_id = uuid4(), uuid4()
        original, raw_token = await service.issue(user_id=user_id, tenant_id=tenant_id)

        # Simulate a concurrent request winning the rotation first.
        now = datetime.now(timezone.utc)
        winning_successor = await refresh_token_repo.rotate(
            current_token_hash=hash_token(raw_token),
            new_token_hash="winning-successor-hash",
            expires_at=now + timedelta(minutes=15),
            rotated_at=now,
        )

        # The losing request, still holding the now-stale raw_token,
        # arrives via the service.
        with pytest.raises(RefreshTokenReuseDetectedError):
            await service.rotate(raw_token=raw_token)

        # The WINNING successor — legitimately obtained — is now also
        # revoked as a consequence of the family-wide revocation.
        winning_after = await refresh_token_repo.get_by_token_hash(
            token_hash="winning-successor-hash"
        )
        assert winning_after.status.value == "revoked"
        assert winning_after.id == winning_successor.id

    async def test_revoked_token_raises_invalid_not_reuse(self, service):
        """A revoked (e.g. logged-out) token must never be classified as
        reuse — only an already-ROTATED token is genuine theft evidence."""
        user_id, tenant_id = uuid4(), uuid4()
        _, raw_token = await service.issue(user_id=user_id, tenant_id=tenant_id)
        await service.revoke_current_session(raw_token=raw_token)

        with pytest.raises(InvalidRefreshTokenError):
            await service.rotate(raw_token=raw_token)

    async def test_expired_token_raises_invalid_not_reuse(
        self, service, refresh_token_repo
    ):
        """An expired token must never be classified as reuse either.
        No sleep needed — constructs an already-expired-but-
        structurally-valid record directly (both issued_at and
        expires_at in the past), now that create() accepts issued_at
        explicitly."""
        now = datetime.now(timezone.utc)
        raw_token = "a-known-raw-token"
        await refresh_token_repo.create(
            user_id=uuid4(),
            tenant_id=uuid4(),
            family_id=uuid4(),
            token_hash=hash_token(raw_token),
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )

        with pytest.raises(InvalidRefreshTokenError):
            await service.rotate(raw_token=raw_token)


class TestRevokeCurrentSession:
    async def test_revokes_the_family(self, service, refresh_token_repo):
        user_id, tenant_id = uuid4(), uuid4()
        _, raw_token = await service.issue(user_id=user_id, tenant_id=tenant_id)

        await service.revoke_current_session(raw_token=raw_token)

        after = await refresh_token_repo.get_by_token_hash(
            token_hash=hash_token(raw_token)
        )
        assert after.status.value == "revoked"

    async def test_is_idempotent_for_unknown_token(self, service):
        """Logout with a token that was never issued must be a no-op,
        not an error — matches the idempotent logout design."""
        await service.revoke_current_session(raw_token="never-issued")  # no raise

    async def test_is_idempotent_for_already_revoked_token(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        _, raw_token = await service.issue(user_id=user_id, tenant_id=tenant_id)
        await service.revoke_current_session(raw_token=raw_token)

        await service.revoke_current_session(raw_token=raw_token)  # no raise, repeat


class TestRevokeAllForTenant:
    async def test_revokes_all_families_for_tenant_only(
        self, service, refresh_token_repo
    ):
        user_id, tenant_a, tenant_b = uuid4(), uuid4(), uuid4()
        _, raw_1 = await service.issue(user_id=user_id, tenant_id=tenant_a)
        _, raw_2 = await service.issue(user_id=user_id, tenant_id=tenant_a)
        _, raw_3_other_tenant = await service.issue(user_id=user_id, tenant_id=tenant_b)

        count = await service.revoke_all_for_tenant(user_id=user_id, tenant_id=tenant_a)
        assert count == 2

        t1 = await refresh_token_repo.get_by_token_hash(token_hash=hash_token(raw_1))
        t2 = await refresh_token_repo.get_by_token_hash(token_hash=hash_token(raw_2))
        t3 = await refresh_token_repo.get_by_token_hash(
            token_hash=hash_token(raw_3_other_tenant)
        )
        assert t1.status.value == "revoked"
        assert t2.status.value == "revoked"
        assert t3.status.value == "active"
