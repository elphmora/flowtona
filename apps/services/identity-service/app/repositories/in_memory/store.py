"""
app/repositories/in_memory/store.py

Shared in-memory persistence boundary for all six repository
implementations (Decision 9). One store instance is passed into every
InMemory*Repository's constructor, so multi-repository workflows
(signup: User -> Tenant -> TenantMembership) share one consistent view
of state, rather than each repository holding an isolated, unrelated
dict.

Deliberately boring: explicit typed dict/set indexes per lookup pattern
actually needed, not a generic indexing framework (no store.add_index(),
no store.query()). Each repository owns updating its own primary
collection and secondary indexes together, inside the lock, so they
never drift out of sync with each other.
"""

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from app.models.email_verification import EmailVerification
from app.models.invitation import Invitation
from app.models.membership import TenantMembership
from app.models.refresh_token import RefreshTokenRecord
from app.models.tenant import Tenant
from app.models.user import User


@dataclass
class InMemoryIdentityStore:
    # Concurrency: a single lock shared across every repository operating
    # on this store. In pure asyncio (no internal awaits mid-method) this
    # isn't strictly required for correctness — but the Protocol
    # docstrings already promise atomicity (e.g. mark_rotated: "concurrent
    # attempts to rotate the same token must not both succeed"), and this
    # makes that guarantee real and self-documenting rather than an
    # accident of the current implementation having no await points. Not
    # intended to mimic real database performance — just deterministic
    # Phase 1 semantics.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    users_by_id: dict[UUID, User] = field(default_factory=dict)
    user_id_by_email: dict[str, UUID] = field(default_factory=dict)

    tenants_by_id: dict[UUID, Tenant] = field(default_factory=dict)

    memberships_by_id: dict[UUID, TenantMembership] = field(default_factory=dict)
    membership_id_by_user_tenant: dict[tuple[UUID, UUID], UUID] = field(
        default_factory=dict
    )
    # list, not set — GET /v1/users/me lists a user's memberships, and
    # sets have no guaranteed iteration order. Insertion order (roughly
    # "joined tenant A, then tenant B") is a reasonable, deterministic
    # default; refresh_token_ids_by_family below stays a set since
    # revocation order genuinely doesn't matter there.
    membership_ids_by_user: dict[UUID, list[UUID]] = field(default_factory=dict)

    invitations_by_id: dict[UUID, Invitation] = field(default_factory=dict)
    invitation_id_by_token_hash: dict[str, UUID] = field(default_factory=dict)

    email_verifications_by_id: dict[UUID, EmailVerification] = field(
        default_factory=dict
    )
    email_verification_id_by_token_hash: dict[str, UUID] = field(default_factory=dict)

    refresh_tokens_by_id: dict[UUID, RefreshTokenRecord] = field(default_factory=dict)
    refresh_token_id_by_hash: dict[str, UUID] = field(default_factory=dict)
    refresh_token_ids_by_family: dict[UUID, set[UUID]] = field(default_factory=dict)
