"""
tests/unit/repositories/test_in_memory_job_repository.py

Covers InMemoryJobRepository's actual contract: basic create/get,
cross-tenant isolation, and aggregate isolation in BOTH directions
(deep-copy-on-write AND deep-copy-on-read) -- the second of those is
easy to silently miss (deep-copy-on-write alone doesn't guarantee it),
so it's tested explicitly rather than assumed.

list_by_tenant() tests (Query Operations checkpoint) additionally
cover: tenant isolation intrinsic to the filter (never optional),
status/client_id filtering (independently and combined), total
computed before pagination, offset/limit slicing, and the explicit
(created_at, id) total ordering -- proven genuine by deliberately creating
jobs with created_at values OUT of insertion order, so a test passing
only by accident of dict iteration order would fail.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.models.job import Job, JobStatus, SiteAddressSnapshot
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


# ---------------------------------------------------------------------------
# list_by_tenant() -- Query Operations checkpoint
# ---------------------------------------------------------------------------


async def test_list_by_tenant_returns_only_jobs_for_the_given_tenant(
    repo: InMemoryJobRepository,
) -> None:
    """Two Jobs in tenant A, one in tenant B -- proves tenant
    filtering doesn't accidentally reduce the legitimate tenant set to
    a single result, not just that tenant B doesn't leak in."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    job_a1 = _make_job(tenant_a)
    job_a2 = _make_job(tenant_a)
    job_b = _make_job(tenant_b)
    await repo.create(job_a1)
    await repo.create(job_a2)
    await repo.create(job_b)

    page = await repo.list_by_tenant(tenant_id=tenant_a)

    assert {job.id for job in page.items} == {job_a1.id, job_a2.id}
    assert page.total == 2


async def test_list_by_tenant_filters_by_status(repo: InMemoryJobRepository) -> None:
    tenant_id = uuid4()
    draft_job = _make_job(tenant_id)
    await repo.create(draft_job)

    cancelled_job = _make_job(tenant_id)
    cancelled_job.status = JobStatus.CANCELLED
    await repo.create(cancelled_job)

    page = await repo.list_by_tenant(tenant_id=tenant_id, status=JobStatus.DRAFT)

    assert [job.id for job in page.items] == [draft_job.id]
    assert page.total == 1


async def test_list_by_tenant_filters_by_client_id(repo: InMemoryJobRepository) -> None:
    tenant_id = uuid4()
    target_client_id = uuid4()

    matching_job = _make_job(tenant_id)
    matching_job.client_id = target_client_id
    await repo.create(matching_job)

    other_job = _make_job(tenant_id)
    await repo.create(other_job)

    page = await repo.list_by_tenant(tenant_id=tenant_id, client_id=target_client_id)

    assert [job.id for job in page.items] == [matching_job.id]
    assert page.total == 1


async def test_list_by_tenant_combines_status_and_client_id_filters(
    repo: InMemoryJobRepository,
) -> None:
    tenant_id = uuid4()
    target_client_id = uuid4()

    matches_both = _make_job(tenant_id)
    matches_both.client_id = target_client_id
    await repo.create(matches_both)

    matches_client_only = _make_job(tenant_id)
    matches_client_only.client_id = target_client_id
    matches_client_only.status = JobStatus.CANCELLED
    await repo.create(matches_client_only)

    matches_status_only = _make_job(tenant_id)
    await repo.create(matches_status_only)

    page = await repo.list_by_tenant(
        tenant_id=tenant_id, status=JobStatus.DRAFT, client_id=target_client_id
    )

    assert [job.id for job in page.items] == [matches_both.id]
    assert page.total == 1


async def test_list_by_tenant_total_reflects_all_matching_before_pagination(
    repo: InMemoryJobRepository,
) -> None:
    tenant_id = uuid4()
    for _ in range(5):
        await repo.create(_make_job(tenant_id))

    page = await repo.list_by_tenant(tenant_id=tenant_id, limit=2, offset=0)

    assert page.total == 5
    assert len(page.items) == 2


async def test_list_by_tenant_applies_offset_and_limit(
    repo: InMemoryJobRepository,
) -> None:
    tenant_id = uuid4()
    jobs: list[Job] = []
    for i in range(5):
        job = _make_job(tenant_id)
        job.created_at = datetime(2026, 1, 1 + i, tzinfo=UTC)
        jobs.append(job)
        await repo.create(job)

    page = await repo.list_by_tenant(tenant_id=tenant_id, limit=2, offset=2)

    assert [job.id for job in page.items] == [jobs[2].id, jobs[3].id]
    assert page.total == 5


async def test_list_by_tenant_orders_by_created_at_ascending(
    repo: InMemoryJobRepository,
) -> None:
    """Proves the explicit sort is genuinely applied, not merely
    matching dict insertion order by accident -- job_later is CREATED
    (inserted) first but given an EARLIER created_at, so a correct
    implementation must still return job_earlier first."""
    tenant_id = uuid4()
    job_later = _make_job(tenant_id)
    job_later.created_at = datetime(2026, 1, 2, tzinfo=UTC)
    await repo.create(job_later)

    job_earlier = _make_job(tenant_id)
    job_earlier.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    await repo.create(job_earlier)

    page = await repo.list_by_tenant(tenant_id=tenant_id)

    assert [job.id for job in page.items] == [job_earlier.id, job_later.id]


async def test_list_by_tenant_uses_job_id_as_tiebreaker_when_created_at_is_equal(
    repo: InMemoryJobRepository,
) -> None:
    """Turns "deterministic ordering" from a documentation claim into
    an actually-tested contract. created_at alone doesn't guarantee a
    total ordering -- two Jobs can share the same value -- so id is
    included as an explicit tie-breaker. Inserted in the OPPOSITE
    order to the expected id ordering, so a test passing only by
    accident of insertion/dict order would fail."""
    tenant_id = uuid4()
    same_created_at = datetime(2026, 1, 1, tzinfo=UTC)

    job_a = _make_job(tenant_id)
    job_b = _make_job(tenant_id)
    job_a.created_at = same_created_at
    job_b.created_at = same_created_at

    first, second = sorted([job_a, job_b], key=lambda job: str(job.id))
    await repo.create(second)
    await repo.create(first)

    page = await repo.list_by_tenant(tenant_id=tenant_id)

    assert [job.id for job in page.items] == [first.id, second.id]


async def test_list_by_tenant_deep_copies_results(repo: InMemoryJobRepository) -> None:
    """Matches get()'s own established isolation guarantee -- a
    caller mutating a Job returned from list_by_tenant() must not
    corrupt the repository's internal state."""
    tenant_id = uuid4()
    job = _make_job(tenant_id)
    await repo.create(job)

    page = await repo.list_by_tenant(tenant_id=tenant_id)
    page.items[0].title = "Mutated after list_by_tenant() -- should not affect storage"

    second_page = await repo.list_by_tenant(tenant_id=tenant_id)

    assert second_page.items[0].title == "Annual boiler service"
