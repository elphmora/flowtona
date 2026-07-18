"""
app/repositories/refresh_token_repository.py

Protocol contract for refresh-token persistence (Decision 9). Entity
model: single RefreshTokenRecord row per issued token — no separate
family/session entity (ADR Invariant 10). family_id groups the tokens
produced by one continuous rotation chain, originating from one login/
device — a family IS one device/session. A user may hold multiple
concurrent families for the same tenant, one per active login/device
(Invariant 10).

rotate() replaces the earlier mark_rotated() + separate create() pair
— fixed 2026-07-17. The original two-call sequence had a real
correctness gap: if mark_rotated() succeeded but the successor create()
then failed (or the reverse ordering), the family could end up with
zero active tokens (unusable session) or two simultaneously active
tokens (breaking the "at most one active token per family" invariant
reuse detection depends on). rotate() does both mutations under one
atomic operation.

ConcurrentUpdateError.actual_state distinguishes WHY a rotation was
refused — already-rotated (genuine reuse), revoked, or expired.
Deliberately not three separate exception classes: the exception
vocabulary stays small, and actual_state already exists specifically
to carry this kind of detail. Callers MUST distinguish already-rotated
from the other two — only already-rotated is genuine reuse; treating a
revoked or expired token hit during a race window as reuse would be a
false-positive theft signal.

create() takes issued_at explicitly, not generated internally — fixed
2026-07-17 alongside rotate(). Previously the service computed
expires_at from its own datetime.now() call while the repository
independently generated issued_at from a SEPARATE datetime.now() call
— two different clock reads for one logical "when did this happen"
moment. Also enables constructing already-expired-but-structurally-
valid test records directly through this public method (issued_at and
expires_at both in the past), avoiding sleep-based test flakiness
without needing a Clock abstraction.

revoke_family() and revoke_all_for_tenant() (renamed 2026-07-17 from
revoke_all_active — the old name was misleading, since it revokes
every NON-REVOKED row including rotated ancestors, not just rows
currently in "active" status) return a row count, not a session/family
count — two device sessions with several rotations between them could
report six rows changed, not two sessions terminated. If a session
count is ever needed, count distinct family_id values, not just rows.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.models.refresh_token import RefreshTokenRecord


class RefreshTokenRepository(Protocol):
    async def create(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        family_id: UUID,
        token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        """Create a new refresh-token row, starting a NEW family. Used
        on login (Flow 1/3) — NOT for rotation, which uses rotate()
        below to stay within the existing family."""
        ...

    async def get_by_token_hash(self, *, token_hash: str) -> RefreshTokenRecord | None:
        """Look up a token by its hash. Callers check `.status`
        themselves for the common-case classification (active/rotated/
        revoked) before deciding whether to call rotate() — but rotate()
        remains the actual race-safe final guard regardless of what this
        lookup returned."""
        ...

    async def rotate(
        self,
        *,
        current_token_hash: str,
        new_token_hash: str,
        expires_at: datetime,
        rotated_at: datetime,
    ) -> RefreshTokenRecord:
        """Atomically rotate an active refresh token: confirms the
        current token exists, is active, and is unexpired; creates an
        active successor in the SAME family (successor's issued_at =
        rotated_at — one timestamp for one logical moment); marks the
        current token rotated with replaced_by_token_id referencing the
        successor. Returns the successor record. No observable mutation
        occurs if any precondition check fails.

        Raises:
            RecordNotFoundError: current_token_hash doesn't exist.
            ConcurrentUpdateError: transition refused — check
                .actual_state ("rotated", "revoked", or "expired") to
                distinguish genuine reuse (rotated) from the other two.
            DuplicateEntryError: new_token_hash already exists
                (astronomically unlikely given generate_secure_token()'s
                entropy — checked anyway, and the caller — RefreshTokenService
                — retries with a freshly generated token rather than
                letting this leak past the service boundary).
        """
        ...

    async def revoke_family(self, *, family_id: UUID, revoked_at: datetime) -> int:
        """Revoke every non-revoked row in the family, including the
        active leaf and rotated ancestors — not just the current token.
        Used for current-device logout (Flow 9 — a family IS one
        device/session, so ending it means terminating the whole chain)
        and refresh-token reuse detection (Flow 5). Returns the count
        of rows revoked."""
        ...

    async def revoke_all_for_tenant(
        self, *, user_id: UUID, tenant_id: UUID, revoked_at: datetime
    ) -> int:
        """Revoke every non-revoked refresh-token row belonging to the
        user and tenant, across ALL token families, including rotated
        historical rows. Called by POST /v1/auth/logout-all (Flow 10).
        Scoped to one tenant only. Returns the count of rows revoked —
        not the number of sessions/families terminated."""
        ...
