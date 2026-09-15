"""
app/models/job.py

Job -- the aggregate root for job-service's Phase 1, scoped to exactly
what Create Job needs.

visits is typed as list[dict[str, object]], constrained to empty by a
field_validator, rather than list[Visit] -- Visit doesn't exist as a
model yet, and Phase 1 provides no aggregate method capable of
populating this list (Job.add_visit() arrives in Phase 2). The
validator makes that invariant explicit rather than relying only on
Job.create()'s signature omitting a visits parameter. When Phase 2
gives Visit its real shape, this becomes list[Visit] and the validator
is removed.

status_history and created_by/changed_by are deliberately absent:
03-api-contract.md's Create Job response has neither field, and
Decision 4's history model only records transitions (each entry has a
from_status) -- creation into draft has no prior status to transition
from, so there's no history entry for it. JobStatusHistory itself
doesn't exist as a model until Phase 4.

completion_summary IS included -- confirmed against the frozen Create
Job response, which explicitly shows "completion_summary": null.

title's non-blank validation is a single inline field_validator, not a
shared NonBlankStr type -- extracting one for a single field, ahead of
a second field/model actually needing the same rule, would be building
shared infrastructure ahead of a concrete second use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobStatus(StrEnum):
    """Full vocabulary per 02-architecture-decisions.md Decision 1.
    Phase 1 only ever produces DRAFT -- naming a closed set of values
    isn't aggregate behavior, so the other values aren't premature."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SiteAddressSnapshot(BaseModel):
    """Immutable copy of Site.address at Job-creation time, per
    01-domain-foundations.md §8. Required/optional split matches
    Client Service's own Site.address validation rules exactly."""

    model_config = ConfigDict(validate_assignment=True)

    line1: str
    line2: str | None = None
    city: str
    postcode: str
    country: str | None = None


class Job(BaseModel):
    """job-service's aggregate root. Phase 1 scope only -- see module
    docstring for what's deliberately absent and why."""

    model_config = ConfigDict(validate_assignment=True)

    id: UUID
    tenant_id: UUID
    status: JobStatus

    title: str
    description: str | None = None
    completion_summary: str | None = None

    client_id: UUID
    client_name_snapshot: str

    site_id: UUID
    site_label_snapshot: str
    site_address_snapshot: SiteAddressSnapshot

    contact_id: UUID | None = None
    contact_name_snapshot: str | None = None
    contact_email_snapshot: str | None = None
    contact_phone_snapshot: str | None = None

    visits: list[dict[str, object]] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value

    @field_validator("visits")
    @classmethod
    def _visits_must_be_empty(
        cls, value: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        if value:
            raise ValueError("visits must be empty in Phase 1")
        return value

    @classmethod
    def create(
        cls,
        *,
        tenant_id: UUID,
        client_id: UUID,
        client_name_snapshot: str,
        site_id: UUID,
        site_label_snapshot: str,
        site_address_snapshot: SiteAddressSnapshot,
        title: str,
        description: str | None = None,
        contact_id: UUID | None = None,
        contact_name_snapshot: str | None = None,
        contact_email_snapshot: str | None = None,
        contact_phone_snapshot: str | None = None,
    ) -> Job:
        """The only aggregate command this phase builds. tenant_id is
        required and keyword-only, passed explicitly by the
        application service from the verified JWT's claim -- never
        accepted from a request body (Platform Conventions §5).

        id, status, visits, and the timestamps are owned by the
        aggregate, not supplied by the caller."""
        now = datetime.now(UTC)
        return cls(
            id=uuid4(),
            tenant_id=tenant_id,
            status=JobStatus.DRAFT,
            title=title,
            description=description,
            completion_summary=None,
            client_id=client_id,
            client_name_snapshot=client_name_snapshot,
            site_id=site_id,
            site_label_snapshot=site_label_snapshot,
            site_address_snapshot=site_address_snapshot,
            contact_id=contact_id,
            contact_name_snapshot=contact_name_snapshot,
            contact_email_snapshot=contact_email_snapshot,
            contact_phone_snapshot=contact_phone_snapshot,
            visits=[],
            created_at=now,
            updated_at=now,
        )
