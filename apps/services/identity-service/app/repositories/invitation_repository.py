"""
app/repositories/invitation_repository.py

Protocol contract for Invitation persistence (Decision 9). Tenant-owned
entity (ADR Decision 2 refinement).

Method names match the repository operations documented in
02-sequence-diagrams.md's Flows 6, 7, and 8.

Token lookup always uses the stored token hash. The raw invitation token
is never accepted by, stored by, or returned from this repository. The
raw token is delivered only through the invitation email.
"""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.constants.roles import Role
from app.models.invitation import Invitation


class InvitationRepository(Protocol):
    async def create(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: Role,
        token_hash: str,
        invited_by_user_id: UUID,
        expires_at: datetime,
    ) -> Invitation:
        """Create a new invitation. Called by POST /v1/tenants/{tenant_id}/
        invites (Flow 6), after the duplicate-membership guard passes."""
        ...

    async def get_by_token_hash(self, *, token_hash: str) -> Invitation | None:
        """Look up an invitation by its token hash. Called at accept time
        for both existing-user (Flow 7) and new-user (Flow 8) paths."""
        ...

    async def mark_accepted(
        self, *, invitation_id: UUID, accepted_at: datetime
    ) -> Invitation:
        """Atomically transition a pending, unexpired invitation to
        accepted. Raise the repository's defined conflict or not-found
        outcome when the invitation is already accepted, expired, or
        otherwise unavailable — this prevents two concurrent acceptance
        requests from both succeeding (conceptually: an UPDATE ... WHERE
        status = pending AND expires_at > now() once on Postgres). The
        repository exception/result model for this hasn't been selected
        yet — that's a separate decision, not implied here.

        Used as part of the invitation-acceptance workflow that also
        creates the TenantMembership. The application must preserve
        all-or-nothing behaviour across those two state changes; this
        contract deliberately does not fix an ordering between them.
        Returns the updated record.
        """
        ...
