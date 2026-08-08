"""
app/models/site.py

Site domain model — client-service-architecture.md Decision 4.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.address import Address
from app.models.types import NonBlankStr, utc_now


class Site(BaseModel):
    """Many-per-Client.

    label is NonBlankStr, same reasoning as Client.name and
    Address.line1/city/postcode — a Site with an empty label isn't a
    meaningful domain object.

    is_primary is scoped per client (not per some other grouping) — at
    most one Site under a given client_id may hold is_primary=True
    (Invariant 2). The first Site created for a client is auto-primary,
    and setting is_primary=True on another Site demotes the previous
    holder. Enforcing that multi-record invariant is SiteService's job,
    not this model's — a domain model here is a typed single-record
    construct, it has no visibility into a client's other sites to
    check the invariant against.

    validate_assignment=True — same reasoning as Client: Site is
    mutable, and service-layer code assigns to fields (e.g.
    site.is_primary = True) before calling SiteRepository.update().
    Without this, label's NonBlankStr check would only run at
    construction, not on assignment.
    """

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    client_id: UUID
    tenant_id: UUID
    label: NonBlankStr
    address: Address
    is_primary: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
