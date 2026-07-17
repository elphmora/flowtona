"""tests/unit/services/test_invitation_service.py"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.constants.roles import Role
from app.exceptions.invitation import InvitationExpiredError, InvitationInvalidError
from app.security.hashing import hash_token
from app.services.invitation_service import InvitationService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service(invitation_repo) -> InvitationService:
    return InvitationService(invitation_repo)


class TestCreate:
    async def test_returns_raw_token_not_the_hash(self, service, invitation_repo):
        invitation, raw_token = await service.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        looked_up_by_raw = await invitation_repo.get_by_token_hash(token_hash=raw_token)
        looked_up_by_hash = await invitation_repo.get_by_token_hash(
            token_hash=hash_token(raw_token)
        )
        assert looked_up_by_raw is None
        assert looked_up_by_hash is not None
        assert looked_up_by_hash.id == invitation.id

    async def test_uses_configured_ttl(self, service):
        from app.core.config import settings

        before = datetime.now(timezone.utc)
        invitation, _ = await service.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        expected_min = before + timedelta(days=settings.INVITATION_TOKEN_EXPIRE_DAYS)
        assert invitation.expires_at >= expected_min - timedelta(seconds=5)


class TestResolvePending:
    async def test_valid_pending_invitation_resolves(self, service):
        _, raw_token = await service.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        resolved = await service.resolve_pending(raw_token=raw_token)
        assert resolved.status.value == "pending"

    async def test_unknown_token_raises_invalid(self, service):
        with pytest.raises(InvitationInvalidError):
            await service.resolve_pending(raw_token="never-issued")

    async def test_already_accepted_raises_invalid(self, service):
        invitation, raw_token = await service.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        await service.mark_accepted(
            invitation_id=invitation.id, accepted_at=datetime.now(timezone.utc)
        )

        with pytest.raises(InvitationInvalidError):
            await service.resolve_pending(raw_token=raw_token)

    async def test_expired_invitation_raises_expired_specifically(
        self, service, invitation_repo
    ):
        """Constructs an expired-but-valid-at-creation record through
        the repository's public create() (short future expiry, then a
        real short sleep past it) — same technique used for
        EmailVerificationService's equivalent test, for the same
        reason: no Clock abstraction exists, and expires_at can never
        be set in the past directly (created_at is always "now" at
        creation time)."""

        raw_token = "a-known-raw-token-for-this-test"
        soon = datetime.now(timezone.utc) + timedelta(milliseconds=50)
        await invitation_repo.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            token_hash=hash_token(raw_token),
            invited_by_user_id=uuid4(),
            expires_at=soon,
        )
        await asyncio.sleep(0.1)

        with pytest.raises(InvitationExpiredError):
            await service.resolve_pending(raw_token=raw_token)


class TestMarkAccepted:
    async def test_accepts_pending_invitation(self, service):
        invitation, _ = await service.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        now = datetime.now(timezone.utc)
        accepted = await service.mark_accepted(
            invitation_id=invitation.id, accepted_at=now
        )
        assert accepted.status.value == "accepted"
        assert accepted.accepted_at == now

    async def test_double_accept_raises_invalid(self, service):
        invitation, _ = await service.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        now = datetime.now(timezone.utc)
        await service.mark_accepted(invitation_id=invitation.id, accepted_at=now)

        with pytest.raises(InvitationInvalidError):
            await service.mark_accepted(invitation_id=invitation.id, accepted_at=now)

    async def test_failed_second_accept_does_not_mutate_record(
        self, service, invitation_repo
    ):
        """A failed re-acceptance attempt must leave the stored record's
        accepted_at exactly as it was from the first, successful
        acceptance — not overwritten, not cleared, zero trace of the
        rejected second attempt."""
        invitation, raw_token = await service.create(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        first_accepted_at = datetime.now(timezone.utc)
        await service.mark_accepted(
            invitation_id=invitation.id, accepted_at=first_accepted_at
        )

        later_attempt = first_accepted_at + timedelta(minutes=5)
        with pytest.raises(InvitationInvalidError):
            await service.mark_accepted(
                invitation_id=invitation.id, accepted_at=later_attempt
            )

        # Bypass the service, check the repository's raw persisted state.
        unchanged = await invitation_repo.get_by_token_hash(
            token_hash=hash_token(raw_token)
        )
        assert unchanged.accepted_at == first_accepted_at


class TestEmailNormalization:
    async def test_created_invitation_email_is_normalized(
        self, service, invitation_repo
    ):
        """InvitationService doesn't normalize itself — normalization
        happens inside InMemoryInvitationRepository.create(), same as
        User/EmailVerification. This confirms that integration point
        actually works end to end through the service."""
        invitation, _ = await service.create(
            tenant_id=uuid4(),
            email="New.Tech@EXAMPLE.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=uuid4(),
        )
        assert invitation.email == "new.tech@example.com"
