"""
app/models/base.py

Shared base for internal domain entities (app/models/*.py).

Distinction that matters here is NOT Pydantic vs. dataclass — it's domain
model vs. HTTP contract (ADR Decision 8 refinement). Domain models must
stay independent of FastAPI request/response concerns: no request aliases,
no HTTP examples, no response-serialization decisions, no endpoint-specific
optionality. Those belong in app/schemas/, which may construct itself from
these models but is never reused as if it were one.
"""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",  # catches accidental fields (e.g. business data on Tenant)
        validate_assignment=True,  # protects invalid transitions on mutation
        from_attributes=True,  # eases future ORM-backed adapters (Postgres) without coupling to one
    )
    # Deliberately not frozen=True — RefreshToken, Invitation, and
    # TenantMembership all have real lifecycle transitions (active -> rotated,
    # pending -> accepted, active -> revoked). Revisit once it's clear
    # whether immutable entities + model_copy(update=...) actually improve
    # this codebase, rather than assuming it up front.
