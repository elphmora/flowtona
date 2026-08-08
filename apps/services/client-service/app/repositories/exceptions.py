"""
app/repositories/exceptions.py

Persistence-oriented exceptions raised by repository implementations
(Platform Conventions §4). Field names intentionally match the platform
repository-exception convention established by identity-service
(entity/field, entity/identifier, entity/identifier/expected_state/
actual_state). A repository doesn't know the business meaning of a
conflict — it raises one of these, and the service layer catches it
and translates it into a workflow-specific domain exception.

One deliberate divergence from identity-service: `identifier` is typed
UUID here, not Any. identity-service types it Any because its actual
usage needs it — RefreshTokenRepository.rotate() raises
RecordNotFoundError with a string token hash, not a UUID. client-
service currently has no repository operation whose identifier is
anything other than UUID — every identifier across ClientRepository/
SiteRepository/ContactRepository (client_id, site_id, contact_id) is
one. Any here would surrender real mypy protection for flexibility this
service doesn't currently need. If a genuine non-UUID identifier
appears later, revisit the type then.

ImmutableFieldError's `expected`/`actual` fields stay Any, deliberately
not narrowed the same way `identifier` was — they hold whatever value
the mismatched field actually carries, which varies per field
(currently always UUID for tenant_id/client_id, but this exception
isn't scoped to those two fields specifically, and a future
identity-defining field on some entity could be a different type).

RecordArchivedError is new here, not present in identity-service's
equivalent file. client-service is the first service with a genuinely
terminal, fully-immutable record state (Client.status == ARCHIVED,
Decision 5). Kept generic (entity/identifier, not Client-specific) not
because another service could import this class — this module lives
inside client-service, nothing outside it should import from here —
but so the name stays meaningful if client-service's own domain later
gains a second archivable entity, without needing a rename.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass
class DuplicateEntryError(Exception):
    """Raised when a create() call would violate a uniqueness
    constraint the repository enforces as the final guard — re-checked
    inside the same lock acquisition that performs the write."""

    entity: str
    field: str


@dataclass
class RecordNotFoundError(Exception):
    """Raised by a mutation method (update/delete/archive/etc.) when
    the targeted record no longer exists at write time. Never raised by
    get_*()/list_*() methods, which return None or an empty result on
    absence."""

    entity: str
    identifier: UUID


@dataclass
class ConcurrentUpdateError(Exception):
    """Raised when an atomic multi-effect operation's precondition
    doesn't hold at write time. actual_state carries what the record's
    real state was found to be, so a caller can distinguish why the
    operation was refused rather than treating every refusal
    identically."""

    entity: str
    identifier: UUID
    expected_state: str
    actual_state: str


@dataclass
class RecordArchivedError(Exception):
    """Raised when any write is attempted against a record whose
    status is a terminal, fully-immutable state (Client.status ==
    ARCHIVED — Decision 5). Enforced here, at the repository, as the
    final guard — not only at the service layer."""

    entity: str
    identifier: UUID


@dataclass
class ImmutableFieldError(Exception):
    """Raised when update() is called with an identity-defining field
    (e.g. tenant_id, client_id) changed from its stored value. Such
    fields define a record's identity and repository index keys —
    silently rewriting them would corrupt those indexes. A deliberate
    rejection, not missing functionality; NotImplementedError would
    misleadingly suggest the opposite.

    expected/actual carry the stored value and the caller's attempted
    value, so a production log line from this exception is enough to
    diagnose the mismatch without needing to reproduce it."""

    entity: str
    field: str
    identifier: UUID
    expected: Any
    actual: Any
