"""
app/repositories/exceptions.py

Persistence-oriented exceptions raised by repository implementations
(Platform Conventions §4). A repository doesn't know the business
meaning of a conflict — it raises one of these, and the service layer
catches it and translates it into a workflow-specific domain exception.
Ordinary lookup methods (get_by_id, list_*) are unaffected by this file
entirely — they continue to return None / an empty list on absence,
never raise, matching identity-service's own convention.

RecordArchivedError is new here, not present in identity-service's
equivalent file. client-service is the first service with a genuinely
terminal, fully-immutable record state (Client.status == ARCHIVED,
client-service-architecture.md Decision 5) — identity-service's own
lifecycle states (TenantMembership.status, RefreshToken rotation
states) don't have this "no further writes, ever" shape. Kept generic
(entity_name/entity_id, not Client-specific) so a later service with a
similar terminal-state pattern can reuse it rather than inventing its
own equivalent.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass
class DuplicateEntryError(Exception):
    """Raised when a create() call would violate a uniqueness
    constraint the repository enforces as the final guard — re-checked
    inside the same lock acquisition that performs the write, not only
    relying on an earlier service-layer check (same reasoning as
    identity-service's repository exception model)."""

    entity_name: str
    conflicting_field: str
    conflicting_value: Any


@dataclass
class RecordNotFoundError(Exception):
    """Raised by a mutation method (update/delete/archive/etc.) when
    the targeted record no longer exists at write time — a genuine
    race-condition safety net, distinct from an ordinary lookup
    returning None. Never raised by get_*()/list_*() methods, which
    return None or an empty result on absence."""

    entity_name: str
    entity_id: UUID


@dataclass
class ConcurrentUpdateError(Exception):
    """Raised when an atomic multi-effect operation's precondition
    doesn't hold at write time (e.g. a record isn't in the state a
    transition requires). actual_state carries what the record's real
    state was found to be, so a caller can distinguish why the
    operation was refused rather than treating every refusal
    identically — same shape as identity-service's
    RefreshTokenRepository.rotate()."""

    entity_name: str
    entity_id: UUID
    expected_state: str
    actual_state: str


@dataclass
class RecordArchivedError(Exception):
    """Raised when any write is attempted against a record whose
    status is a terminal, fully-immutable state (e.g. Client.status ==
    ARCHIVED — Decision 5). Enforced here, at the repository, as the
    final guard — not only at the service layer — the same reasoning
    identity-service applies to uniqueness via DuplicateEntryError."""

    entity_name: str
    entity_id: UUID
