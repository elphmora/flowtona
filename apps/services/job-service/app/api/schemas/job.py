"""
app/api/schemas/job.py

Request/response schemas for POST /v1/jobs, per 03-api-contract.md.
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

JobResponse.visits -- corrected during review. list[dict[str, object]]
alone was flagged as an API contract weaker than both the domain and
the eventual intent: even constrained to empty at runtime, the type
itself presents to any API consumer (via generated OpenAPI docs) as
"array of arbitrary objects," with no signal that this is a deliberate
Phase 1 limitation rather than a genuinely open-ended field. Rejected
alternatives: list[Never] (same "untested exotic Pydantic construct"
risk already rejected once for the domain model itself) and
Literal[[]] (invalid -- lists aren't hashable, so Literal can't express
this). The fix: keep the same boring, certain-to-work type, but make
the limitation explicit and OpenAPI-visible via Field(description=...),
plus the same empty-constraint field_validator Job's own domain model
already has -- defense-in-depth, not solely relying on the upstream
guarantee that job.visits is already empty by the time this runs.

JobResponse is a distinct class from app.models.job.Job even though
both are Pydantic -- matching the established platform-wide
convention of never reusing a domain model as an API schema directly.
from_domain() is the one translation point.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.job import Job


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

    visits: list[dict[str, object]] = Field(
        default_factory=list,
        description=(
            "Always empty in Phase 1 -- Visit behavior is deliberately "
            "deferred from the Create Job slice. This field exists to "
            'match the frozen 03-api-contract.md response shape ("visits": '
            "[]) and will gain a real VisitResponse element type when "
            "Visit is implemented."
        ),
    )

    created_at: datetime
    updated_at: datetime

    @field_validator("visits")
    @classmethod
    def _visits_must_be_empty(
        cls, value: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        if value:
            raise ValueError("visits must be empty in Phase 1")
        return value

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
            visits=job.visits,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
