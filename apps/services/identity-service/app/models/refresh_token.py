"""
app/models/refresh_token.py

Tenant-owned entity (ADR Decision 2 refinement). This is the
RefreshTokenRecord type referenced in
app/repositories/refresh_token_repository.py's Protocol.

Single-entity model per Invariant 10 and the sequence-diagrams doc's
"Correct model" note — no separate RefreshSession/family entity.
family_id groups rows from one continuous rotation chain (one login/
device). A user may hold multiple concurrent families per tenant.

status stays active/rotated/revoked only — no stored EXPIRED status
(deferred 2026-07-12). Expiry is checked against expires_at at lookup
time rather than tracked as a stored transition, since a stored EXPIRED
status would require something (a sweep job) to actively set it, and
that's real infrastructure with no design behind it yet.

Structural validation only here (expiry ordering, replaced_by_token_id
consistency) — workflow logic like actually revoking a family or
incrementing permissions_version belongs in services/, not in the model.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from app.models.base import DomainModel


class RefreshTokenStatus(StrEnum):
    ACTIVE = "active"
    ROTATED = "rotated"
    REVOKED = "revoked"


class RefreshTokenRecord(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    tenant_id: UUID
    family_id: UUID
    token_hash: str
    status: RefreshTokenStatus = RefreshTokenStatus.ACTIVE
    issued_at: datetime
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None
    replaced_by_token_id: UUID | None = None

    @model_validator(mode="after")
    def _check_expiry_ordering(self) -> "RefreshTokenRecord":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")
        return self

    @model_validator(mode="after")
    def _check_replaced_by_only_when_rotated(self) -> "RefreshTokenRecord":
        if (
            self.replaced_by_token_id is not None
            and self.status != RefreshTokenStatus.ROTATED
        ):
            raise ValueError(
                "replaced_by_token_id may only be set when status is 'rotated'"
            )
        return self

    @model_validator(mode="after")
    def _check_rotated_at_present_when_rotated(self) -> "RefreshTokenRecord":
        if self.status == RefreshTokenStatus.ROTATED and self.rotated_at is None:
            raise ValueError("rotated_at is required when status is 'rotated'")
        return self

    @model_validator(mode="after")
    def _check_revoked_at_present_when_revoked(self) -> "RefreshTokenRecord":
        if self.status == RefreshTokenStatus.REVOKED and self.revoked_at is None:
            raise ValueError("revoked_at is required when status is 'revoked'")
        return self
