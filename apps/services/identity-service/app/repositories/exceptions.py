"""
app/repositories/exceptions.py

Generic, infrastructure-level exceptions raised by repository
implementations on conflict — deliberately not the same vocabulary as
app/exceptions/ (service-layer domain exceptions, per Decision 8's flow:
service raises domain exceptions, route translates to HTTP).

Repositories know persistence-level facts (an index already contains
this key, a targeted row doesn't exist, a state-transition precondition
wasn't met) — not what those facts mean in business terms. The same
DuplicateEntryError from UserRepository.create() during signup and from
a different repository during an unrelated workflow can mean entirely
different things; only the service layer, which has that context,
should be translating to something workflow-specific like
EmailAlreadyRegisteredError.

This is also the shape persistence errors will take once Postgres
exists — a generic IntegrityError-style signal gets translated at the
service boundary, not baked into the persistence layer itself.

Structured context (entity/field), not bare strings — but never the
actual value for sensitive fields (email, token hashes). Exception
messages and logs shouldn't carry secrets or PII any more than any
other part of this codebase does.
"""

from typing import Any


class RepositoryError(Exception):
    """Base class for all repository-layer exceptions."""


class DuplicateEntryError(RepositoryError):
    """A uniqueness constraint prevented a write."""

    def __init__(self, *, entity: str, field: str, value: Any | None = None) -> None:
        self.entity = entity
        self.field = field
        self.value = value
        super().__init__(f"duplicate {entity} for field {field!r}")


class RecordNotFoundError(RepositoryError):
    """A mutation targeted a record that doesn't exist. Not used for
    ordinary lookups — those already return None; this is only for
    mutation methods where absence means the requested transition
    couldn't happen at all."""

    def __init__(self, *, entity: str, identifier: Any) -> None:
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} {identifier} not found")


class ConcurrentUpdateError(RepositoryError):
    """A state-transition precondition wasn't met — e.g. mark_rotated()
    called on a token that isn't currently active, or mark_accepted()
    called on an invitation that's already accepted or expired. Covers
    both genuine race conditions and simple staleness (the precondition
    became false over time, not because of a concurrent request) —
    callers handle both the same way: reject the transition."""

    def __init__(
        self,
        *,
        entity: str,
        identifier: Any,
        expected_state: str | None = None,
        actual_state: str | None = None,
    ) -> None:
        self.entity = entity
        self.identifier = identifier
        self.expected_state = expected_state
        self.actual_state = actual_state
        super().__init__(
            f"{entity} {identifier} was not in the expected state "
            f"(expected={expected_state!r}, actual={actual_state!r})"
        )
