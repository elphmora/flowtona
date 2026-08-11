"""
app/api/schemas/client.py

Request/response schemas for /v1/clients. tenant_id is NEVER accepted
in any request schema (Platform Conventions §5) — every request model
uses ConfigDict(extra="forbid") so a client-supplied tenant_id, or any
other undeclared field, is rejected with 422, not silently stripped.

name reuses NonBlankStr directly from app.models.types rather than
re-approximating the same rule with a separate min_length/regex — one
definition of "what counts as a non-blank name," shared by both the
HTTP request boundary and the domain model, rather than two rules that
could drift apart.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.api.schemas.contact import ContactResponse
from app.api.schemas.site import SiteResponse
from app.models.client import Client
from app.models.contact import Contact
from app.models.enums import ClientStatus, ClientType
from app.models.site import Site
from app.models.types import NonBlankStr


class ClientCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonBlankStr
    client_type: ClientType


class ClientUpdateRequest(BaseModel):
    """Partial update — all fields optional, only supplied ones are
    changed. status is restricted to ACTIVE<->INACTIVE at the service
    layer (ClientService.update_client() rejects ARCHIVED outright,
    raising ArchiveViaUpdateNotAllowedError); not re-validated here,
    since the service-layer rule is the authoritative one and
    duplicating it in the schema (e.g. via a narrower enum) would risk
    the two drifting out of sync."""

    model_config = ConfigDict(extra="forbid")

    name: NonBlankStr | None = None
    client_type: ClientType | None = None
    status: ClientStatus | None = None


class ClientResponse(BaseModel):
    """Full shape — used by POST, GET (single), and PATCH responses.
    Distinct from ClientListItem below (Decision 6): this one carries
    populated sites/contacts arrays, not just counts."""

    id: UUID
    tenant_id: UUID
    name: str
    client_type: ClientType
    status: ClientStatus
    sites: list[SiteResponse]
    contacts: list[ContactResponse]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(
        cls, client: Client, *, sites: list[Site], contacts: list[Contact]
    ) -> "ClientResponse":
        return cls(
            id=client.id,
            tenant_id=client.tenant_id,
            name=client.name,
            client_type=client.client_type,
            status=client.status,
            sites=[SiteResponse.from_domain(s) for s in sites],
            contacts=[ContactResponse.from_domain(c) for c in contacts],
            created_at=client.created_at,
            updated_at=client.updated_at,
        )


class ClientListItem(BaseModel):
    """Summary shape for GET /v1/clients — site_count/contact_count,
    not full nested arrays (Decision 6), so list payload weight
    doesn't scale with per-client subresource counts."""

    id: UUID
    name: str
    client_type: ClientType
    status: ClientStatus
    site_count: int
    contact_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(
        cls, client: Client, *, site_count: int, contact_count: int
    ) -> "ClientListItem":
        return cls(
            id=client.id,
            name=client.name,
            client_type=client.client_type,
            status=client.status,
            site_count=site_count,
            contact_count=contact_count,
            created_at=client.created_at,
            updated_at=client.updated_at,
        )


class ClientListResponse(BaseModel):
    """Pagination envelope (Decision 7) — only GET /v1/clients uses
    this shape; subresource list endpoints (sites, contacts) return
    plain arrays, not this envelope."""

    items: list[ClientListItem]
    total: int
    limit: int
    offset: int
