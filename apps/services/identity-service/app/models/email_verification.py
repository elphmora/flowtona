"""
app/models/email_verification.py

Email-verification record for one user and one specific email address.
Added 2026-07-14 — discovered as a missing sixth entity while writing
UserRepository's Protocol (a naive fix would have put a short-lived
credential's fields directly on User; this is the corrected version).

Global entity, not tenant-owned (ADR Decision 2 refinement) — email
verification is a User-level concern, independent of tenant context,
consistent with User itself having no tenant_id.

The raw verification token is never persisted, only its hash — same
discipline as Invitation.token_hash and RefreshTokenRecord.token_hash.

REVOKED exists because POST /v1/auth/email/resend (already in
01-api-contract.md) issues a new token on each call — the previous
pending one needs to be distinguishable as superseded, not just
abandoned. This is NOT justified by "email change," which isn't a
decided feature anywhere in the ADR or API contract.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import EmailStr, Field, model_validator

from app.models.base import DomainModel


class EmailVerificationStatus(StrEnum):
    PENDING = "pending"
    CONSUMED = "consumed"
    REVOKED = "revoked"


class EmailVerification(DomainModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    email: EmailStr
    token_hash: str
    status: EmailVerificationStatus = EmailVerificationStatus.PENDING
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    revoked_at: datetime | None = None

    @model_validator(mode="after")
    def _check_status_timestamps(self) -> "EmailVerification":
        """Single combined validator, not several independent ones — this
        entity's three states have genuine mutual-exclusivity requirements
        between them (e.g. a PENDING record must have neither timestamp,
        a CONSUMED one must never also carry revoked_at), which is clearer
        to reason about in one place than split across separate checks."""
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")

        if self.status == EmailVerificationStatus.PENDING:
            if self.consumed_at is not None or self.revoked_at is not None:
                raise ValueError(
                    "pending verification cannot have consumed_at or revoked_at"
                )

        if self.status == EmailVerificationStatus.CONSUMED:
            if self.consumed_at is None:
                raise ValueError("consumed_at is required when status is 'consumed'")
            if self.revoked_at is not None:
                raise ValueError("consumed verification cannot have revoked_at")

        if self.status == EmailVerificationStatus.REVOKED:
            if self.revoked_at is None:
                raise ValueError("revoked_at is required when status is 'revoked'")
            if self.consumed_at is not None:
                raise ValueError("revoked verification cannot have consumed_at")

        return self
