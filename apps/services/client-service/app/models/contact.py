"""
app/models/contact.py

Contact domain model — client-service-architecture.md Decision 4.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.types import NonBlankStr, utc_now


class Contact(BaseModel):
    """Many-per-Client, optionally scoped to one Site via site_id.

    site_id=None means a client-level contact (e.g. billing); a set
    value means the contact is scoped to that specific site. Deleting a
    Site nulls site_id on any Contact pointing at it (Decision 4, 9) —
    never cascades. is_primary follows the same at-most-one-per-client
    rule as Site.is_primary (Invariant 2), enforced by ContactService,
    not here, for the same reason noted on Site.

    name is NonBlankStr, same reasoning as Client.name/Site.label/
    Address.line1,city,postcode. email/phone use a different kind of
    domain invariant, below — not "this field can't be blank" but
    "at least one of these two optional fields must be present."
    """

    model_config = ConfigDict(frozen=False)

    id: UUID = Field(default_factory=uuid4)
    client_id: UUID
    tenant_id: UUID
    site_id: UUID | None = None
    name: NonBlankStr
    role: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    is_primary: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> Contact:
        """Decision 8: a Contact with neither email nor phone is not
        addressable and not useful.

        Enforced here, at the domain model, so this invariant holds for
        every construction path, including a service constructing a
        Contact directly (e.g. a future import/migration workflow) that
        doesn't go through a request schema at all — same rationale as
        NonBlankStr above, just for a completeness check across two
        optional fields rather than a single required one.
        """
        if not self.email and not self.phone:
            raise ValueError("Contact requires at least one of email or phone")
        return self
