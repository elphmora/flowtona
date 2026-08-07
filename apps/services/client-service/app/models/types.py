"""
app/models/types.py

Reusable field-level types for domain models.

This is the home for domain-vocabulary types shared across models —
not a private implementation detail (hence no leading underscore, and
the plain `types` name rather than `_validators`). NonBlankStr is the
first entry; TenantScopedUUID, EmailAddress, or similar are natural
future additions here as the same "type-valid but not domain-
meaningful" gap shows up elsewhere.

NonBlankStr closes that specific gap for required string fields: a
plain `str` with no default already requires *presence* at
construction (Pydantic rejects missing/None for every construction
path — HTTP, import, CLI, tests alike). It does not reject an empty or
whitespace-only string, which is syntactically valid but not a
meaningful value for a field like Client.name or Address.city. This
type closes that gap, and only that gap — it does not do trimming,
max-length, or any HTTP-specific formatting; those stay at the API
schema layer per Decision 8, since they're about how raw input is
cleaned, not about whether the domain object can be meaningfully
constructed at all.

utc_now() replaces the `default_factory=lambda: datetime.now(timezone.
utc)` that was previously repeated at every created_at/updated_at field
across Client, Site, and Contact — six call sites for the same one-line
lambda. Consistent with identity-service's own choice not to introduce
a Clock abstraction (nothing here needs deterministic time control in
tests yet, per its Entity & Convention Clarifications) — this is purely
deduplication, not a testability seam.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator

# ----------------------------------------------------------------------
# Reusable field types
# ----------------------------------------------------------------------


def _reject_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlankStr = Annotated[str, AfterValidator(_reject_blank)]

# ----------------------------------------------------------------------
# Shared default factories
# ----------------------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
