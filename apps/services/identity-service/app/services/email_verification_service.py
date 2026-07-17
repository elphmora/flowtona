"""
app/services/email_verification_service.py

Owns the email-verification credential lifecycle — create, verify,
resend. Does NOT mark User.email_verified itself, and does NOT bump
any TenantMembership.permissions_version — that's AuthService's job,
composing this service with UserService and MembershipService (the
soft gate lifting affects every membership a user holds, which is a
cross-entity concern outside this service's scope; see the ADR's
Entity & Convention Clarifications on why permissions_version lives on
TenantMembership, not User).

verify() is a single atomic method, not split into a separate
"resolve" + "consume" step. Consuming FIRST, as one atomic repository
call, means a double-click or retried request fails cleanly at this
one gate before any downstream User/Membership state is touched —
preferred over consuming last, which would let two near-simultaneous
calls both pass a pre-check and both reach the downstream updates
before only one consume() succeeds (see the ADR's Deferred Decisions:
Unit of Work entry for the full reasoning on this ordering).

Token TTL comes from Settings (Decision 7's "configurable, not
hardcoded" principle, applied the same way to this token's lifetime).
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.config import settings
from app.exceptions.email_verification import (
    VerificationTokenExpiredError,
    VerificationTokenInvalidError,
)
from app.models.email_verification import EmailVerification, EmailVerificationStatus
from app.repositories.email_verification_repository import EmailVerificationRepository
from app.repositories.exceptions import ConcurrentUpdateError
from app.security.hashing import generate_secure_token, hash_token


class EmailVerificationService:
    def __init__(self, verification_repo: EmailVerificationRepository) -> None:
        self._verification_repo = verification_repo

    async def create(self, *, user_id: UUID, email: str) -> str:
        """Generates a raw token, hashes it, persists the hash, returns
        the RAW token — the caller (AuthService) is responsible for
        actually delivering it (email). The raw token is never
        persisted or logged anywhere past this point."""
        raw_token = generate_secure_token()
        token_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(
            hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS
        )
        await self._verification_repo.create(
            user_id=user_id,
            email=email,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        return raw_token

    async def verify(self, *, raw_token: str) -> EmailVerification:
        """Consume-first design (see module docstring). Pre-checks
        status/expiry against the fetched record to raise the precise
        domain exception in the common case (VerificationTokenInvalidError
        vs. VerificationTokenExpiredError distinguished cleanly) — but
        the actual repository-level mark_consumed() call remains the
        real, race-safe final guard for the narrow window between the
        pre-check and this call. A race lost at that final guard
        collapses to the generic invalid-token error rather than trying
        to distinguish exactly why it was lost."""
        token_hash = hash_token(raw_token)
        verification = await self._verification_repo.get_by_token_hash(
            token_hash=token_hash
        )
        if verification is None:
            raise VerificationTokenInvalidError()

        now = datetime.now(timezone.utc)

        if verification.status != EmailVerificationStatus.PENDING:
            raise VerificationTokenInvalidError()

        if verification.expires_at <= now:
            raise VerificationTokenExpiredError()

        try:
            return await self._verification_repo.mark_consumed(
                verification_id=verification.id, consumed_at=now
            )
        except ConcurrentUpdateError as exc:
            raise VerificationTokenInvalidError() from exc

    async def resend(self, *, user_id: UUID, email: str) -> str:
        """Revokes every still-pending record for this user, then issues
        a fresh one — so an old, un-clicked link can't be used after a
        newer one has been sent."""
        now = datetime.now(timezone.utc)
        await self._verification_repo.revoke_pending_for_user(
            user_id=user_id, revoked_at=now
        )
        return await self.create(user_id=user_id, email=email)
