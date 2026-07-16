"""
app/models/invitation.py

Tenant-owned entity (ADR Decision 2 refinement). Backs the invite-only
teammate addition flow (Decision 10).

token_hash, not the raw token — per the API contract, the raw invite
token is never returned by any endpoint and is only ever delivered via
the invite email, so it must never be persisted or logged in plaintext.

status stays pending/accepted/expired only — no REVOKED status (deferred
2026-07-12). There is no "revoke an invite" endpoint anywhere in the API
contract; adding the status now would mean modeling state with no code
path that ever sets it. Add when that endpoint is actually designed.

invited_by_user_id added for audit traceability (Decision 17 observability
— useful to know who sent an invite, not just that one exists).
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import EmailStr, Field, model_validator

from app.constants.roles import Role
from app.models.base import DomainModel


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"


class Invitation(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    email: EmailStr
    role: Role
    token_hash: str
    status: InvitationStatus = InvitationStatus.PENDING
    invited_by_user_id: UUID
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None

    @model_validator(mode="after")
    def _check_expiry_ordering(self) -> "Invitation":
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return self

    @model_validator(mode="after")
    def _check_accepted_at_present_when_accepted(self) -> "Invitation":
        if self.status == InvitationStatus.ACCEPTED and self.accepted_at is None:
            raise ValueError("accepted_at is required when status is 'accepted'")
        return self
