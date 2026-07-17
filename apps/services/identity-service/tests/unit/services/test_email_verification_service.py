"""tests/unit/services/test_email_verification_service.py"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.exceptions.email_verification import (
    VerificationTokenExpiredError,
    VerificationTokenInvalidError,
)
from app.security.hashing import hash_token
from app.services.email_verification_service import EmailVerificationService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service(email_verification_repo) -> EmailVerificationService:
    return EmailVerificationService(email_verification_repo)


class TestCreate:
    async def test_returns_raw_token_not_the_hash(
        self, service, email_verification_repo
    ):
        user_id = uuid4()
        raw_token = await service.create(user_id=user_id, email="dana@example.com")

        # the raw token must not be directly retrievable AS a token_hash —
        # only its hash should exist in the repository
        looked_up_by_raw = await email_verification_repo.get_by_token_hash(
            token_hash=raw_token
        )
        looked_up_by_hash = await email_verification_repo.get_by_token_hash(
            token_hash=hash_token(raw_token)
        )
        assert looked_up_by_raw is None
        assert looked_up_by_hash is not None

    async def test_expiry_uses_configured_ttl(self, service, email_verification_repo):
        from app.core.config import settings

        user_id = uuid4()
        before = datetime.now(timezone.utc)
        raw_token = await service.create(user_id=user_id, email="dana@example.com")
        verification = await email_verification_repo.get_by_token_hash(
            token_hash=hash_token(raw_token)
        )
        expected_min = before + timedelta(
            hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS
        )
        # allow a small margin for test execution time
        assert verification.expires_at >= expected_min - timedelta(seconds=5)


class TestVerify:
    async def test_valid_token_is_consumed(self, service):
        raw_token = await service.create(user_id=uuid4(), email="dana@example.com")
        result = await service.verify(raw_token=raw_token)
        assert result.status.value == "consumed"

    async def test_unknown_token_raises_invalid(self, service):
        with pytest.raises(VerificationTokenInvalidError):
            await service.verify(raw_token="this-token-was-never-issued")

    async def test_already_consumed_token_raises_invalid(self, service):
        raw_token = await service.create(user_id=uuid4(), email="dana@example.com")
        await service.verify(raw_token=raw_token)

        with pytest.raises(VerificationTokenInvalidError):
            await service.verify(raw_token=raw_token)

    async def test_expired_token_raises_expired_specifically(
        self, email_verification_repo
    ):
        """Distinguishes the two error types — expired must NOT collapse
        into the generic invalid-token error, matching
        01-api-contract.md's 410 vs. generic-invalid distinction.

        Constructs the record with a very short but genuinely future
        expiry through the repository's public create(), then actually
        waits past it — NOT expires_at set in the past directly, which
        would violate EmailVerification's own "expires_at must be later
        than created_at" validator (created_at is always "now" at
        creation time; a record can never be born already-expired).
        No Clock abstraction exists (deliberately deferred elsewhere in
        this project), so a real short sleep is the correct tool here,
        not a private-attribute shortcut."""
        raw_token = "a-known-raw-token-for-this-test"
        soon = datetime.now(timezone.utc) + timedelta(milliseconds=50)
        await email_verification_repo.create(
            user_id=uuid4(),
            email="dana@example.com",
            token_hash=hash_token(raw_token),
            expires_at=soon,
        )
        await asyncio.sleep(0.1)  # comfortably past the 50ms expiry above
        service = EmailVerificationService(email_verification_repo)

        with pytest.raises(VerificationTokenExpiredError):
            await service.verify(raw_token=raw_token)

    async def test_failed_verification_does_not_mutate_record(
        self, service, email_verification_repo
    ):
        """A failed re-verification attempt on an already-consumed
        record must leave the stored record's state exactly as it was
        — the atomic guard shouldn't just reject the second attempt,
        it should leave zero trace of having touched the record."""
        raw_token = await service.create(user_id=uuid4(), email="dana@example.com")
        first_result = await service.verify(raw_token=raw_token)

        with pytest.raises(VerificationTokenInvalidError):
            await service.verify(raw_token=raw_token)

        unchanged = await email_verification_repo.get_by_token_hash(
            token_hash=hash_token(raw_token)
        )
        assert unchanged.consumed_at == first_result.consumed_at
        assert unchanged.status == first_result.status


class TestResend:
    async def test_revokes_old_pending_and_issues_new(
        self, service, email_verification_repo
    ):
        user_id = uuid4()
        old_raw_token = await service.create(user_id=user_id, email="dana@example.com")

        new_raw_token = await service.resend(user_id=user_id, email="dana@example.com")

        assert new_raw_token != old_raw_token

        old_verification = await email_verification_repo.get_by_token_hash(
            token_hash=hash_token(old_raw_token)
        )
        assert old_verification.status.value == "revoked"

        # the new token must still verify successfully
        result = await service.verify(raw_token=new_raw_token)
        assert result.status.value == "consumed"

    async def test_old_token_no_longer_verifiable_after_resend(self, service):
        user_id = uuid4()
        old_raw_token = await service.create(user_id=user_id, email="dana@example.com")
        await service.resend(user_id=user_id, email="dana@example.com")

        with pytest.raises(VerificationTokenInvalidError):
            await service.verify(raw_token=old_raw_token)
