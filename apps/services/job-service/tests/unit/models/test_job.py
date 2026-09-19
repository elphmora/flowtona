"""
tests/unit/models/test_job.py

Job.create() is the only aggregate command Phase 1 builds -- these
tests establish its behavior before anything is built on top of it.

Phase 2 (PR 1) adds Job.add_visit(): the tests below establish which
source statuses accept a new Visit, which are rejected as terminal,
and what the mutation does to both the new Visit and the parent Job.
"""

from datetime import UTC
from uuid import UUID, uuid4

import pytest

from app.exceptions.job import JobTerminalError
from app.models.job import Job, JobStatus, SiteAddressSnapshot, VisitStatus


def _valid_address() -> SiteAddressSnapshot:
    return SiteAddressSnapshot(
        line1="14 Colmore Row",
        city="Birmingham",
        postcode="B3 2QD",
    )


def _base_kwargs() -> dict:
    """Shared minimum-required arguments for Job.create(), so each
    test only overrides what it's actually testing."""
    return {
        "tenant_id": uuid4(),
        "client_id": uuid4(),
        "client_name_snapshot": "Birmingham Plumbing Co.",
        "site_id": uuid4(),
        "site_label_snapshot": "Main Warehouse",
        "site_address_snapshot": _valid_address(),
        "title": "Annual boiler service",
    }


def test_create_generates_a_uuid() -> None:
    job = Job.create(**_base_kwargs())
    assert isinstance(job.id, UUID)


def test_create_preserves_tenant_id() -> None:
    tenant_id = uuid4()
    job = Job.create(**{**_base_kwargs(), "tenant_id": tenant_id})
    assert job.tenant_id == tenant_id


def test_create_status_is_draft() -> None:
    job = Job.create(**_base_kwargs())
    assert job.status == JobStatus.DRAFT


def test_create_captures_every_supplied_snapshot_exactly() -> None:
    address = SiteAddressSnapshot(
        line1="1 Example Street",
        line2="Unit 4",
        city="Leeds",
        postcode="LS1 1AA",
        country="UK",
    )
    kwargs = {
        **_base_kwargs(),
        "client_name_snapshot": "Leeds Heating Ltd.",
        "site_label_snapshot": "North Depot",
        "site_address_snapshot": address,
        "contact_id": uuid4(),
        "contact_name_snapshot": "Sam Okafor",
        "contact_email_snapshot": "sam@leedsheating.co.uk",
        "contact_phone_snapshot": "+44 113 000 0000",
    }
    job = Job.create(**kwargs)

    assert job.client_name_snapshot == "Leeds Heating Ltd."
    assert job.site_label_snapshot == "North Depot"
    assert job.site_address_snapshot == address
    assert job.contact_id == kwargs["contact_id"]
    assert job.contact_name_snapshot == "Sam Okafor"
    assert job.contact_email_snapshot == "sam@leedsheating.co.uk"
    assert job.contact_phone_snapshot == "+44 113 000 0000"


def test_create_optional_contact_snapshot_can_be_absent() -> None:
    job = Job.create(**_base_kwargs())
    assert job.contact_id is None
    assert job.contact_name_snapshot is None
    assert job.contact_email_snapshot is None
    assert job.contact_phone_snapshot is None


def test_create_visits_is_empty() -> None:
    job = Job.create(**_base_kwargs())
    assert job.visits == []


def test_create_timestamps_are_equal_at_creation() -> None:
    job = Job.create(**_base_kwargs())
    assert job.created_at == job.updated_at


def test_create_timestamps_are_utc_aware() -> None:
    job = Job.create(**_base_kwargs())
    assert job.created_at.tzinfo is not None
    assert job.created_at.tzinfo == UTC
    assert job.updated_at.tzinfo == UTC


@pytest.mark.parametrize("blank_title", ["", "   ", "\t\n"])
def test_create_rejects_blank_title(blank_title: str) -> None:
    with pytest.raises(ValueError, match="title must not be blank"):
        Job.create(**{**_base_kwargs(), "title": blank_title})


# ---------------------------------------------------------------------------
# Job.add_visit() -- Phase 2, PR 1 (Domain + Repository)
# ---------------------------------------------------------------------------


def test_add_visit_creates_draft_visit() -> None:
    job = Job.create(**_base_kwargs())

    visit = job.add_visit()

    assert visit.job_id == job.id
    assert visit.status == VisitStatus.DRAFT
    assert job.visits == [visit]


def test_add_visit_creates_visit_without_schedule_assignment_or_outcome() -> None:
    """add_visit() takes no arguments -- Create Visit's request body is
    {} per the frozen command contract. This proves the resulting
    Visit carries none of the command-owned fields that later,
    separate commands (Schedule, Assign, Complete) are responsible
    for -- it does not, and cannot, pin the Python signature itself."""
    job = Job.create(**_base_kwargs())

    visit = job.add_visit()

    assert visit.scheduled_start is None
    assert visit.scheduled_end is None
    assert visit.actual_start is None
    assert visit.actual_end is None
    assert visit.assigned_member_id is None
    assert visit.outcome_code is None
    assert visit.completion_notes is None


@pytest.mark.parametrize(
    "status",
    [JobStatus.DRAFT, JobStatus.SCHEDULED, JobStatus.IN_PROGRESS],
)
def test_add_visit_is_allowed_for_mutable_job_statuses(status: JobStatus) -> None:
    job = Job.create(**_base_kwargs())
    job.status = status

    visit = job.add_visit()

    assert visit in job.visits


@pytest.mark.parametrize(
    "status",
    [JobStatus.COMPLETED, JobStatus.CANCELLED],
)
def test_add_visit_rejects_terminal_job_statuses(status: JobStatus) -> None:
    job = Job.create(**_base_kwargs())
    job.status = status

    with pytest.raises(JobTerminalError):
        job.add_visit()

    assert job.visits == []


def test_add_visit_uses_one_timestamp_for_visit_creation_and_job_update() -> None:
    """The deterministic invariant: the aggregate deliberately uses the
    same `now` for the new Visit and the parent mutation. This
    verifies that invariant directly rather than relying on the clock
    advancing between two operations."""
    job = Job.create(**_base_kwargs())

    visit = job.add_visit()

    assert visit.created_at == visit.updated_at
    assert job.updated_at == visit.updated_at
    assert visit.created_at.tzinfo == UTC


def test_add_visit_generates_distinct_visit_ids() -> None:
    job = Job.create(**_base_kwargs())

    first = job.add_visit()
    second = job.add_visit()

    assert first.id != second.id
    assert job.visits == [first, second]
