"""
app/repositories/membership_repository.py

Protocol contract for TenantMembership persistence (Decision 9).
Tenant-owned entity (ADR Decision 2 refinement) — every method here is
scoped by tenant_id and/or user_id, never by fields TenantMembership
doesn't own (e.g. email — see the correction note in
02-sequence-diagrams.md's Flow 6, where a composite
MembershipRepo.get_membership_by_email() call was split into
UserRepo.get_by_email() + this repository's get_by_user_and_tenant()).
"""

from typing import Protocol
from uuid import UUID

from app.constants.roles import Role
from app.models.membership import TenantMembership


class MembershipRepository(Protocol):
    async def create(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role: Role,
    ) -> TenantMembership:
        """Create a new membership. Called on signup (Flow 1, role=owner),
        and invite acceptance (Flows 7/8, role=invite.role)."""
        ...

    async def get_by_user_and_tenant(
        self, *, user_id: UUID, tenant_id: UUID
    ) -> TenantMembership | None:
        """The core existence check — used both for tenant-selection
        (Flow 3) and for the invite-creation duplicate-membership guard
        (Flow 6), the latter only after the caller has already resolved
        an email to a user_id via UserRepository.get_by_email()."""
        ...

    async def get_memberships_for_user(
        self, *, user_id: UUID
    ) -> list[TenantMembership]:
        """All of a user's memberships across every tenant — powers
        GET /v1/users/me (Decision 2's global-User rationale) and the
        multi-membership login flow (Flow 3). Order is a genuine
        contract guarantee, not an in-memory implementation accident:
        results must preserve a stable, deterministic order (insertion
        order is the current choice) — GET /v1/users/me presents this
        list to the end user, and a Postgres implementation must include
        an explicit ORDER BY to honor this same guarantee."""
        ...

    async def update(self, *, membership: TenantMembership) -> TenantMembership:
        """Persist status changes to a single membership. Takes the full
        updated model, same reasoning as UserRepository.update(). NOT
        used for permissions_version bumps across multiple memberships —
        see bump_permissions_version_for_user() below for that bulk case."""
        ...

    async def bump_permissions_version_for_user(
        self, *, user_id: UUID
    ) -> list[TenantMembership]:
        """Atomically increment permissions_version on every membership
        belonging to the supplied user. Same shape as
        RefreshTokenRepository.revoke_family()/revoke_all_active() — a
        bulk state change, not a service-level loop. This makes the
        bump-across-memberships step atomic; the larger workflow calling
        it (consume EmailVerification + update User + this bump) is
        still not atomic as a whole — see the ADR's Deferred Decisions:
        Unit of Work entry for that separate, still-open concern.
        Returns the updated memberships."""
        ...
