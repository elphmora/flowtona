"""
app/api/schemas/site.py

Read-only response shape only — used to embed a client's sites in
GET/POST /v1/clients/{client_id} (Decision 6). Create/update request
schemas and the dedicated /v1/clients/{client_id}/sites routes belong
to feature/client-service-sites-api, not this branch — this file
exists now only because the client detail response needs to render
sites that already exist.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.api.schemas.address import AddressResponse
from app.models.site import Site


class SiteResponse(BaseModel):
    id: UUID
    client_id: UUID
    tenant_id: UUID
    label: str
    address: AddressResponse
    is_primary: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, site: Site) -> "SiteResponse":
        return cls(
            id=site.id,
            client_id=site.client_id,
            tenant_id=site.tenant_id,
            label=site.label,
            address=AddressResponse(**site.address.model_dump()),
            is_primary=site.is_primary,
            created_at=site.created_at,
            updated_at=site.updated_at,
        )
