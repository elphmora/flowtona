"""
app/models/client.py

Client domain model — client-service-architecture.md Decision 4, 5.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ClientStatus, ClientType
from app.models.types import NonBlankStr, utc_now


class Client(BaseModel):
    """Tenant-owned root entity. Every Site and Contact points back to
    exactly one Client (Decision 4).

    name is NonBlankStr — a Client with an empty/whitespace-only name
    isn't a meaningful domain object, the same reasoning applied to
    Address.line1/city/postcode and Site.label.

    tenant_id is present here per Platform Conventions §5, but its only
    legitimate origin anywhere in the call stack is a verified JWT
    claim — this model doesn't enforce that itself (a domain model has
    no way to know where a value came from), the repository/service
    layers do, per Decision 2's structural rule.

    validate_assignment=True (matching identity-service's User) —
    Client is deliberately mutable, and service-layer code will assign
    to fields (e.g. client.name = new_name) before handing the model to
    ClientRepository.update(). Without this, NonBlankStr's validator
    only runs at construction — an assignment like client.name = "   "
    would silently succeed. This closes that gap the same way
    construction-time validation already does.
    """

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    name: NonBlankStr
    client_type: ClientType
    status: ClientStatus = ClientStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
