"""
app/models/contact.py

Contact domain model — client-service-architecture.md Decision 4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
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

    validate_assignment=True so domain invariants are enforced on
    attribute updates as well as construction. The email-or-phone
    invariant intentionally uses `mode="before"` so a failed assignment
    is rejected before mutating the instance, rather than after — see
    client-service-architecture.md's Entity & Convention Clarifications
    for the full reasoning and the experiment that confirmed it.
    """

    model_config = ConfigDict(frozen=False, validate_assignment=True)

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

    @model_validator(mode="before")
    @classmethod
    def _require_email_or_phone(cls, data: Any) -> Any:
        """Decision 8: a Contact with neither email nor phone is not
        addressable and not useful. mode="before" deliberately — see
        the class docstring. isinstance(data, dict) guards against a
        non-dict input shape; under the Pydantic version this project
        uses, assignment was confirmed to always pass a dict here, but
        the guard costs nothing and protects against a future Pydantic
        version changing that observed (not contractually guaranteed)
        behavior.
        """
        if isinstance(data, dict) and not data.get("email") and not data.get("phone"):
            raise ValueError("Contact requires at least one of email or phone")
        return data
