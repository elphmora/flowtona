"""
app/repositories/in_memory/email_verification_repository.py

In-memory implementation of EmailVerificationRepository (Protocol,
Decision 9).

email is normalized the same way as UserRepository (app/utils/email.py)
— so the defensive "verification.email == user.email" check in Flow 1
compares two values normalized the same way, rather than potentially
failing on casing alone.

mark_consumed() now checks expiry as part of its atomic guard, not just
status == PENDING — added 2026-07-17 while building EmailVerificationService.
InvitationRepository.mark_accepted() already enforced expiry
(expires_at <= accepted_at); this repository's equivalent guard didn't,
which was an inconsistency between two structurally identical entities
(both token-hash-based, single-use, time-limited), not a deliberate
design choice.

State transitions (mark_consumed, revoke_pending_for_user) reconstruct
the full model via model_dump() + the constructor, NOT
model_copy(update=...) — model_copy does not run Pydantic validators,
which would silently defeat EmailVerification's mutual-exclusivity
validator (a bug in the update dict could produce an invalid stored
object with no error at all). Reconstructing through the constructor
validates the complete final state atomically.

revoke_pending_for_user() has no dedicated by-user index — it's a linear
scan over email_verifications_by_id filtered by user_id and PENDING
status. Deliberate: this method is only called on resend, which is rare
per user, so a dedicated index would be overhead with no real payoff —
consistent with not building a generic indexing framework.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.models.email_verification import EmailVerification, EmailVerificationStatus
from app.repositories.exceptions import (
    ConcurrentUpdateError,
    DuplicateEntryError,
    RecordNotFoundError,
)
from app.repositories.in_memory.store import InMemoryIdentityStore
from app.utils.email import normalise_email


class InMemoryEmailVerificationRepository:
    def __init__(self, store: InMemoryIdentityStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        user_id: UUID,
        email: str,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailVerification:
        normalized = normalise_email(email)

        async with self._store.lock:
            if token_hash in self._store.email_verification_id_by_token_hash:
                raise DuplicateEntryError(
                    entity="email_verification", field="token_hash"
                )

            verification = EmailVerification(
                user_id=user_id,
                email=normalized,
                token_hash=token_hash,
                created_at=datetime.now(timezone.utc),
                expires_at=expires_at,
            )
            stored = verification.model_copy(deep=True)
            self._store.email_verifications_by_id[verification.id] = stored
            self._store.email_verification_id_by_token_hash[token_hash] = (
                verification.id
            )
            return stored.model_copy(deep=True)

    async def get_by_token_hash(self, *, token_hash: str) -> EmailVerification | None:
        verification_id = self._store.email_verification_id_by_token_hash.get(
            token_hash
        )
        if verification_id is None:
            return None
        return self._store.email_verifications_by_id[verification_id].model_copy(
            deep=True
        )

    async def mark_consumed(
        self, *, verification_id: UUID, consumed_at: datetime
    ) -> EmailVerification:
        async with self._store.lock:
            verification = self._store.email_verifications_by_id.get(verification_id)
            if verification is None:
                raise RecordNotFoundError(
                    entity="email_verification", identifier=verification_id
                )

            if verification.status != EmailVerificationStatus.PENDING:
                raise ConcurrentUpdateError(
                    entity="email_verification",
                    identifier=verification_id,
                    expected_state="pending",
                    actual_state=verification.status.value,
                )

            if verification.expires_at <= consumed_at:
                raise ConcurrentUpdateError(
                    entity="email_verification",
                    identifier=verification_id,
                    expected_state="unexpired",
                    actual_state="expired",
                )

            data = verification.model_dump()
            data["status"] = EmailVerificationStatus.CONSUMED
            data["consumed_at"] = consumed_at
            updated = EmailVerification(**data)

            self._store.email_verifications_by_id[verification_id] = updated.model_copy(
                deep=True
            )
            return updated.model_copy(deep=True)

    async def revoke_pending_for_user(
        self, *, user_id: UUID, revoked_at: datetime
    ) -> int:
        async with self._store.lock:
            count = 0
            for verification_id, verification in list(
                self._store.email_verifications_by_id.items()
            ):
                if (
                    verification.user_id == user_id
                    and verification.status == EmailVerificationStatus.PENDING
                ):
                    data = verification.model_dump()
                    data["status"] = EmailVerificationStatus.REVOKED
                    data["revoked_at"] = revoked_at
                    updated = EmailVerification(**data)
                    self._store.email_verifications_by_id[verification_id] = (
                        updated.model_copy(deep=True)
                    )
                    count += 1
            return count
