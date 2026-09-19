"""
app/models/job.py

Job -- the aggregate root for job-service, extended in Phase 2 (PR 1)
with the Visit child entity and the Create Visit domain command.

visits was list[dict[str, object]], constrained to empty by a
field_validator, through Phase 1 -- Visit didn't exist as a model yet,
and Phase 1 provided no aggregate method capable of populating this
list. Now that Visit has its real shape and Job.add_visit() exists,
visits is list[Visit] and the empty-visits validator is removed: an
empty list is still the natural starting value (default_factory=list),
it's just no longer an enforced invariant.

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

Visit's field set mirrors the already-frozen Visit response shape:
scheduling fields, actual timing fields, assigned_member_id, the
outcome pair (outcome_code/completion_notes), and timestamps. Only
DRAFT is ever produced by add_visit() -- the remaining VisitStatus
values exist because the API contract and metrics surface already name
them; later PRs add the transitions that reach them.

Job.add_visit() takes no arguments and always produces a bare draft
Visit -- Create Visit's request body is {} per the frozen command
contract. Scheduling and assignment are separate, later commands; they
must not be smuggled into this constructor. The terminal-state
invariant (no new Visits once a Job is COMPLETED or CANCELLED) lives
here, on the aggregate, rather than in JobService, so nothing can
construct an invalid Visit-on-terminal-Job state by calling
add_visit() directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.exceptions.job import JobTerminalError


class JobStatus(StrEnum):
    """Full vocabulary per 02-architecture-decisions.md Decision 1.
    Phase 1 only ever produces DRAFT -- naming a closed set of values
    isn't aggregate behavior, so the other values aren't premature."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VisitStatus(StrEnum):
    """Full frozen lifecycle vocabulary for a Visit. Only DRAFT is
    produced today (Phase 2, PR 1): Job.add_visit() always creates a
    Visit in DRAFT status. The remaining values exist because the API
    contract and metrics surface (visit_completed_total,
    visit_cancelled_total{outcome_code}, ...) already name them; later
    PRs add the transitions that reach them."""

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


class Visit(BaseModel):
    """A single Visit belonging to a Job. Constructed only through
    Job.add_visit() -- never directly by application code -- so the
    terminal-state invariant can't be bypassed."""

    model_config = ConfigDict(validate_assignment=True)

    id: UUID
    job_id: UUID
    status: VisitStatus

    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None

    actual_start: datetime | None = None
    actual_end: datetime | None = None

    assigned_member_id: UUID | None = None

    outcome_code: str | None = None
    completion_notes: str | None = None

    created_at: datetime
    updated_at: datetime


class Job(BaseModel):
    """job-service's aggregate root. See module docstring for what's
    deliberately absent and why."""

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

    visits: list[Visit] = Field(default_factory=list)

    created_at: datetime
    updated_at: datetime

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
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
        """The only aggregate command Phase 1 builds. tenant_id is
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

    def add_visit(self) -> Visit:
        """Create Visit: the sole Phase 2 PR 1 command. Takes no
        arguments -- the request body is {} per the frozen command
        contract; scheduling and assignment are separate, later
        commands, not parameters smuggled in here.

        Raises JobTerminalError if this Job is COMPLETED or CANCELLED.
        DRAFT, SCHEDULED, and IN_PROGRESS Jobs may all accept a new
        Visit -- only the two genuinely terminal statuses are
        rejected, so this is a denylist rather than an allowlist of
        permitted source statuses."""
        if self.status in (JobStatus.COMPLETED, JobStatus.CANCELLED):
            raise JobTerminalError(self.id)

        now = datetime.now(UTC)
        visit = Visit(
            id=uuid4(),
            job_id=self.id,
            status=VisitStatus.DRAFT,
            created_at=now,
            updated_at=now,
        )
        self.visits.append(visit)
        self.updated_at = now
        return visit
