"""
app/api/schemas/job.py

Request/response schemas for Job Service's Job API, per
03-api-contract.md.

tenant_id is NEVER accepted in the request schema (Platform
Conventions §5) -- CreateJobRequest uses ConfigDict(extra="forbid") so
a client-supplied tenant_id, or any other undeclared field, is
rejected with 422, not silently stripped.

CreateJobRequest's own title non-blank validator DUPLICATES
Job.create()'s domain-level check -- deliberately, matching
client-service's own confirmed ContactCreateRequest precedent
("a request violating this invariant would fail deep in the
repository layer as an unhandled ValueError rather than a clean 422
at the HTTP boundary"). Without this, a blank title would reach
Job.create(), raise a bare pydantic.ValidationError (not a
RequestValidationError, which only covers FastAPI's own request
parsing), and fall through to the generic 500 handler instead of the
documented 422 validation_failed.

JobResponse.visits -- Phase 2 update: now list[VisitResponse], built
via VisitResponse.from_domain() over the aggregate's real Visit
objects. Through Phase 1 this was list[dict[str, object]] with an
empty-only validator, recorded then as an explicit acceptance item
("the moment Phase 2 introduces a real Visit domain model, this field
MUST change to list[VisitResponse] and _visits_must_be_empty MUST be
removed"). That moment is now -- the validator is gone along with the
placeholder type.

VisitResponse is defined before JobResponse so JobResponse's field
declaration and from_domain() translation refer directly to an
already-defined response schema rather than relying unnecessarily on
forward-reference resolution.

JobResponse and VisitResponse remain distinct from their corresponding
domain models even though both sides use Pydantic -- matching the
established platform-wide convention of never exposing a domain model
as an API schema directly. from_domain() methods are the explicit
translation boundary.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.job import Job, Visit


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: UUID
    site_id: UUID
    contact_id: UUID | None = None
    title: str
    description: str | None = None

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value


class SiteAddressSnapshotResponse(BaseModel):
    line1: str
    line2: str | None
    city: str
    postcode: str
    country: str | None


class VisitResponse(BaseModel):
    """Full Visit representation defined by 03-api-contract.md.

    Translates from the Visit domain model through from_domain(),
    preserving the domain/API boundary used by JobResponse. The same
    response shape is reused by Visit query and command endpoints.
    """

    id: UUID
    job_id: UUID
    status: str
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    actual_start: datetime | None
    actual_end: datetime | None
    assigned_member_id: UUID | None
    outcome_code: str | None
    completion_notes: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, visit: Visit) -> VisitResponse:
        return cls(
            id=visit.id,
            job_id=visit.job_id,
            status=visit.status,
            scheduled_start=visit.scheduled_start,
            scheduled_end=visit.scheduled_end,
            actual_start=visit.actual_start,
            actual_end=visit.actual_end,
            assigned_member_id=visit.assigned_member_id,
            outcome_code=visit.outcome_code,
            completion_notes=visit.completion_notes,
            created_at=visit.created_at,
            updated_at=visit.updated_at,
        )


class JobResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    status: str
    title: str
    description: str | None
    completion_summary: str | None

    client_id: UUID
    client_name_snapshot: str

    site_id: UUID
    site_label_snapshot: str
    site_address_snapshot: SiteAddressSnapshotResponse

    contact_id: UUID | None
    contact_name_snapshot: str | None
    contact_email_snapshot: str | None
    contact_phone_snapshot: str | None

    visits: list[VisitResponse] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, job: Job) -> JobResponse:
        return cls(
            id=job.id,
            tenant_id=job.tenant_id,
            status=job.status,
            title=job.title,
            description=job.description,
            completion_summary=job.completion_summary,
            client_id=job.client_id,
            client_name_snapshot=job.client_name_snapshot,
            site_id=job.site_id,
            site_label_snapshot=job.site_label_snapshot,
            site_address_snapshot=SiteAddressSnapshotResponse(
                line1=job.site_address_snapshot.line1,
                line2=job.site_address_snapshot.line2,
                city=job.site_address_snapshot.city,
                postcode=job.site_address_snapshot.postcode,
                country=job.site_address_snapshot.country,
            ),
            contact_id=job.contact_id,
            contact_name_snapshot=job.contact_name_snapshot,
            contact_email_snapshot=job.contact_email_snapshot,
            contact_phone_snapshot=job.contact_phone_snapshot,
            visits=[VisitResponse.from_domain(visit) for visit in job.visits],
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class JobListItemResponse(BaseModel):
    """Summary shape for GET /v1/jobs -- confirmed directly from
    03-api-contract.md's example response.

    visit_count, not a nested visits array -- list payload weight
    shouldn't scale with per-Job Visit counts (mirroring
    client-service Decision 6's list/detail split). visit_count is
    computed here (len(job.visits)), never stored -- there's no
    persisted counter to keep in sync.
    """

    id: UUID
    status: str
    title: str
    client_id: UUID
    client_name_snapshot: str
    site_label_snapshot: str
    visit_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, job: Job) -> JobListItemResponse:
        return cls(
            id=job.id,
            status=job.status,
            title=job.title,
            client_id=job.client_id,
            client_name_snapshot=job.client_name_snapshot,
            site_label_snapshot=job.site_label_snapshot,
            visit_count=len(job.visits),
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


class JobListResponse(BaseModel):
    """Pagination envelope matching client-service's convention.

    The response shape is items/total/limit/offset, as confirmed by
    03-api-contract.md's Query Operations contract.
    """

    items: list[JobListItemResponse]
    total: int
    limit: int
    offset: int
