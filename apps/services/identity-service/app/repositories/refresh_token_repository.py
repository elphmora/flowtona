"""
app/repositories/refresh_token_repository.py

Protocol contract for refresh-token persistence (Decision 9). Entity model:
single RefreshTokenRecord row per issued token — no separate family/
session entity (ADR Invariant 10, and the sequence-diagrams doc's
"Correct model" note). family_id groups the tokens produced by one
continuous rotation chain, originating from one login/device — a family
IS one device/session. A user may hold multiple concurrent families for
the same tenant, one per active login/device (Invariant 10).

create() takes business fields as keyword arguments, not a pre-built
RefreshTokenRecord — id and issued_at are repository-owned. Matches the
convention used across every other repository Protocol in this branch.

Timestamps (rotated_at, revoked_at) are always passed in explicitly by
the caller, never generated internally via datetime.now() — matches the
style of mark_consumed(..., consumed_at) and mark_accepted(..., accepted_at)
elsewhere in this branch, and keeps tests deterministic.

revoke_token() does not exist here (removed 2026-07-14, before ever
being committed) — see revoke_family()'s docstring for why single-row
revocation doesn't match what "logout" actually means given the family
model.
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
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        """Create a new refresh-token row. Used on login (new family) and
        on rotation (new row within an existing family, Flow 4)."""
        ...

    async def get_by_token_hash(self, *, token_hash: str) -> RefreshTokenRecord | None:
        """Look up a token by its hash. Callers check `.status` themselves
        — `active` means safe to rotate, `rotated` means reuse (Flow 5),
        `revoked` means rejected outright."""
        ...

    async def mark_rotated(
        self,
        *,
        token_hash: str,
        replaced_by_token_id: UUID,
        rotated_at: datetime,
    ) -> RefreshTokenRecord:
        """Atomically transition one active token to rotated.

        The transition must succeed only when the stored token is
        currently active — concurrent attempts to rotate the same token
        must not both succeed (this is the repository-level guard against
        two simultaneous refresh requests both rotating the same row).
        Sets replaced_by_token_id and rotated_at. Returns the updated
        record.
        """
        ...

    async def revoke_family(self, *, family_id: UUID, revoked_at: datetime) -> int:
        """Revoke every non-revoked row in one family, including the
        active leaf and rotated ancestors.

        This is what "logout" actually means: a family represents one
        login/device (Invariant 10), so ending a device's session means
        terminating its whole family, not just whichever single token
        happened to be presented (Flow 9). Also used for refresh-token
        reuse detection (Flow 5), which revokes the compromised family
        entirely. Returns the count revoked.
        """
        ...

    async def revoke_all_active(
        self, *, user_id: UUID, tenant_id: UUID, revoked_at: datetime
    ) -> int:
        """Revoke every non-revoked refresh-token row belonging to the
        user and tenant, across ALL token families, including rotated
        historical rows. Called by POST /v1/auth/logout-all (Flow 10).
        Scoped to one tenant only; see ADR Deferred Decisions for the
        (not yet built) cross-tenant variant. Returns the count revoked.
        """
        ...
