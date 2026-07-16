"""
app/repositories/user_repository.py

Protocol contract for User persistence (Decision 9: Protocol-based,
structural typing). User is the one global (non-tenant-scoped) entity
(ADR Decision 2 refinement) — get_by_email is the one method here that
takes no tenant_id, since which tenant a credential belongs to is only
knowable after the password is checked (see 01-api-contract.md's login
flow).

create() accepts email_verified (default False) — needed for invitation
acceptance by a brand-new user (Invariant 9: accepting an invite
implicitly verifies the invitee's email). Added 2026-07-17 while
building UserService; the original Protocol lacked this, which would
have forced a create-then-update two-step for that path instead of one
atomic creation call.

create() takes business fields as keyword arguments, not a pre-built User
— id and created_at are repository-owned, generated at persistence time,
not by the caller. Matches the call shape already used in
02-sequence-diagrams.md's Flow 1.
"""

from typing import Protocol
from uuid import UUID

from app.models.user import User


class UserRepository(Protocol):
    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        email_verified: bool = False,
    ) -> User:
        """Create a new user. Called during signup (Flow 1, email_verified
        defaults False) and invite acceptance for a new account (Flow 8,
        email_verified=True per Invariant 9)."""
        ...

    async def get_by_id(self, *, user_id: UUID) -> User | None: ...

    async def get_by_email(self, *, email: str) -> User | None:
        """The one tenant-agnostic lookup — needed for login before tenant
        context is known, and for checking email-uniqueness at signup."""
        ...

    async def update(self, *, user: User) -> User:
        """Persist changes to an existing user (e.g. email_verified flip,
        password_hash rotation). Takes the full updated model, unlike
        create() — there's no ambiguity here about what's caller-owned
        vs. repository-owned once the record already exists."""
        ...
