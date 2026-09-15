"""
tests/unit/repositories/test_in_memory_job_repository.py

Covers InMemoryJobRepository's actual contract: basic create/get,
cross-tenant isolation, and aggregate isolation in BOTH directions
(deep-copy-on-write AND deep-copy-on-read) -- the second of those is
easy to silently miss (deep-copy-on-write alone doesn't guarantee it),
so it's tested explicitly rather than assumed.
"""

from uuid import UUID, uuid4

import pytest

from app.models.job import Job, SiteAddressSnapshot
from app.repositories.in_memory.job_repository import InMemoryJobRepository


def _make_job(tenant_id: UUID | None = None) -> Job:
    return Job.create(
        tenant_id=tenant_id or uuid4(),
        client_id=uuid4(),
        client_name_snapshot="Birmingham Plumbing Co.",
        site_id=uuid4(),
        site_label_snapshot="Main Warehouse",
        site_address_snapshot=SiteAddressSnapshot(
            line1="14 Colmore Row", city="Birmingham", postcode="B3 2QD"
        ),
        title="Annual boiler service",
    )


@pytest.fixture
def repo() -> InMemoryJobRepository:
    return InMemoryJobRepository()


async def test_get_returns_none_for_unknown_job_id(repo: InMemoryJobRepository) -> None:
    result = await repo.get(tenant_id=uuid4(), job_id=uuid4())
    assert result is None


async def test_create_then_get_returns_an_equivalent_job(
    repo: InMemoryJobRepository,
) -> None:
    job = _make_job()
    await repo.create(job)

    fetched = await repo.get(tenant_id=job.tenant_id, job_id=job.id)

    assert fetched is not None
    assert fetched == job


async def test_get_returns_none_when_tenant_id_does_not_match(
    repo: InMemoryJobRepository,
) -> None:
    """Cross-tenant isolation enforced at the repository layer -- a
    job_id that genuinely exists, under a different tenant, must be
    indistinguishable from a job_id that doesn't exist at all."""
    job = _make_job()
    await repo.create(job)

    fetched = await repo.get(tenant_id=uuid4(), job_id=job.id)

    assert fetched is None


async def test_create_deep_copies_so_mutating_the_original_does_not_corrupt_storage(
    repo: InMemoryJobRepository,
) -> None:
    job = _make_job()
    await repo.create(job)

    job.title = "Mutated after create() -- should not affect storage"

    fetched = await repo.get(tenant_id=job.tenant_id, job_id=job.id)

    assert fetched is not None
    assert fetched.title == "Annual boiler service"


async def test_get_deep_copies_so_mutating_the_result_does_not_corrupt_storage(
    repo: InMemoryJobRepository,
) -> None:
    """The isolation direction that deep-copy-on-write alone doesn't
    guarantee: a caller mutating what get() handed them must not
    affect what a later get() call returns."""
    job = _make_job()
    await repo.create(job)

    first = await repo.get(tenant_id=job.tenant_id, job_id=job.id)
    assert first is not None
    first.title = "Mutated on the caller's copy -- should not affect storage"

    second = await repo.get(tenant_id=job.tenant_id, job_id=job.id)

    assert second is not None
    assert second.title == "Annual boiler service"


async def test_repeated_get_calls_return_distinct_objects(
    repo: InMemoryJobRepository,
) -> None:
    """Complements the mutation tests above with a direct identity
    check: two get() calls for the same job must never hand back the
    same object instance."""
    job = _make_job()
    await repo.create(job)

    first = await repo.get(tenant_id=job.tenant_id, job_id=job.id)
    second = await repo.get(tenant_id=job.tenant_id, job_id=job.id)

    assert first is not second
