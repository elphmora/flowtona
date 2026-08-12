"""
app/api/schemas/site.py

SiteResponse (read-only) was built in feature/client-service-clients-
api, for embedding a client's sites in GET/POST /v1/clients/{id}.
SiteCreateRequest/SiteUpdateRequest are new here — the request side of
the dedicated /v1/clients/{client_id}/sites routes.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.schemas.address import AddressRequest, AddressResponse
from app.models.site import Site
from app.models.types import NonBlankStr


class SiteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: NonBlankStr
    address: AddressRequest
    is_primary: bool | None = None


class SiteUpdateRequest(BaseModel):
    """Partial update — all fields optional, only supplied ones are
    changed."""

    model_config = ConfigDict(extra="forbid")

    label: NonBlankStr | None = None
    address: AddressRequest | None = None
    is_primary: bool | None = None


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
