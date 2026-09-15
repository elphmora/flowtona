"""
tests/unit/models/test_job.py

Job.create() is the only aggregate command Phase 1 builds -- these
tests establish its behavior before anything is built on top of it.
"""

from datetime import UTC
from uuid import UUID, uuid4

import pytest

from app.models.job import Job, JobStatus, SiteAddressSnapshot


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
