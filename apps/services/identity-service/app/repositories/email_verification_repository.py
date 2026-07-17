"""
app/repositories/email_verification_repository.py

Protocol contract for EmailVerification persistence (Decision 9). Global
entity, not tenant-owned — see app/models/email_verification.py.

mark_consumed() atomically requires status == PENDING AND
expires_at > consumed_at — added 2026-07-17, matching
InvitationRepository.mark_accepted()'s equivalent expiry guard. An
earlier version of this method only checked status, which was an
inconsistency between two structurally identical entities (both
token-hash-based, single-use, time-limited), not a deliberate choice.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.models.email_verification import EmailVerification


class EmailVerificationRepository(Protocol):
    async def create(
        self,
        *,
        user_id: UUID,
        email: str,
        token_hash: str,
        expires_at: datetime,
    ) -> EmailVerification:
        """Create a new verification record. Called on signup (Flow 1) and
        on each POST /v1/auth/email/resend call."""
        ...

    async def get_by_token_hash(self, *, token_hash: str) -> EmailVerification | None:
        """Look up a verification record by its token hash. Called by
        POST /v1/auth/email/verify (Flow 1)."""
        ...

    async def mark_consumed(
        self, *, verification_id: UUID, consumed_at: datetime
    ) -> EmailVerification:
        """Atomically transition one pending, unexpired verification
        record to consumed. Must succeed only when status is PENDING
        and expires_at > consumed_at — concurrent/duplicate attempts,
        or an attempt after expiry, must not succeed. Returns the
        updated record."""
        ...

    async def revoke_pending_for_user(
        self, *, user_id: UUID, revoked_at: datetime
    ) -> int:
        """Revoke every still-pending verification record for a user —
        called before issuing a fresh one on resend, so an old token
        can't be used after a newer one has been issued. Returns the
        count revoked (a bulk operation — the individual revoked records
        aren't needed by any caller, unlike mark_consumed's single
        transition)."""
        ...
