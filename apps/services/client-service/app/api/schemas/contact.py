"""
app/api/schemas/contact.py

Read-only response shape only — same reasoning as
app/api/schemas/site.py. Create/update request schemas and the
dedicated /v1/clients/{client_id}/contacts routes belong to
feature/client-service-contacts-api, not this branch.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.contact import Contact


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
