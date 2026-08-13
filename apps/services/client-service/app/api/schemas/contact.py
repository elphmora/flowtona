"""
app/api/schemas/contact.py

ContactResponse (read-only) was built in feature/client-service-
clients-api, for embedding a client's contacts in GET/POST
/v1/clients/{id}. ContactCreateRequest/ContactUpdateRequest are new
here — the request side of the dedicated
/v1/clients/{client_id}/contacts routes.

ContactCreateRequest enforces email-or-phone itself, via its own
model_validator — not left solely to Contact's own domain-model
validator, which only fires once the repository constructs a real
Contact. Without a schema-level check, a request violating this
invariant would fail deep in the repository layer as an unhandled
ValueError rather than a clean 422 at the HTTP boundary.

ContactUpdateRequest deliberately does NOT attempt this validation —
correct MERGED-state validation is impossible from the request body
alone (it doesn't know the existing contact's current values for
fields not being changed), so this check is exclusively
ContactService's concern for updates, not this schema's.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.models.contact import Contact
from app.models.types import NonBlankStr


class ContactCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonBlankStr
    role: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    site_id: UUID | None = None
    is_primary: bool | None = None

    @model_validator(mode="after")
    def _require_email_or_phone(self) -> "ContactCreateRequest":
        if not self.email and not self.phone:
            raise ValueError("A contact must have at least one of email or phone.")
        return self


class ContactUpdateRequest(BaseModel):
    """Partial update — every field optional. Whether a field was
    actually present in the request (vs. omitted) is read from
    model_fields_set at the route layer, not from this schema's
    values alone — that's what lets the route distinguish "omitted"
    from "explicitly sent as null" when calling
    ContactService.update_contact()'s UNSET-aware parameters."""

    model_config = ConfigDict(extra="forbid")

    name: NonBlankStr | None = None
    role: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    site_id: UUID | None = None
    is_primary: bool | None = None


class ContactResponse(BaseModel):
    id: UUID
    client_id: UUID
    tenant_id: UUID
    site_id: UUID | None
    name: str
    role: str | None
    email: str | None
    phone: str | None
    is_primary: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, contact: Contact) -> "ContactResponse":
        return cls(
            id=contact.id,
            client_id=contact.client_id,
            tenant_id=contact.tenant_id,
            site_id=contact.site_id,
            name=contact.name,
            role=contact.role,
            email=contact.email,
            phone=contact.phone,
            is_primary=contact.is_primary,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
        )
