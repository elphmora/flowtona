"""
app/repositories/in_memory/job_repository.py

InMemoryJobRepository -- the only JobRepository implementation.
Ordinary dict-backed storage inside async method bodies -- no
asyncio.sleep, no executor, no fake concurrency. The async signatures
exist to match the platform-wide repository convention (see
app/repositories/job_repository.py's docstring), not because this
implementation performs any actual I/O.

Full aggregate isolation, both directions, on every method including
the new save():
  - create()/save() store a deep copy of the given Job, so a caller
    mutating their own reference afterward cannot corrupt what's
    persisted.
  - get()/list_by_tenant()/save() return deep copies of the stored
    Jobs, so a caller mutating what they got back cannot corrupt the
    repository's internal state either. Deep-copy-on-write alone
    doesn't guarantee this -- a caller handed a live reference to the
    stored object could still mutate it directly. All directions are
    tested explicitly.

Storage keyed by job.id alone (not a composite tenant_id+id key) --
get()'s and save()'s tenant_id parameters VALIDATE the match rather
than locate the record: a job_id existing under a different tenant is
indistinguishable from not existing at all, rather than a distinct
"found but wrong tenant" case a caller could probe for.

save()'s tenant check is deliberately two-part and does not trust the
provenance of the Job object it's handed:
  1. the currently stored record (if any) must belong to tenant_id;
  2. the Job being saved must itself claim tenant_id.
Either mismatch raises JobNotFoundError. Part 2 is the one that
actually matters: without it, a Job object whose tenant_id had been
changed since it was fetched could move an aggregate from one tenant
to another purely by being passed to save() -- relying on "all current
callers fetched it correctly first" is not a repository invariant,
it's an assumption a later command, test helper, or persistence
implementation could easily violate.

list_by_tenant() filters self._jobs.values() by tenant_id first
(mandatory, never optional), then status/client_id if given, computes
total BEFORE slicing, then applies offset/limit -- one pass, total
falls out naturally, no separate count query needed.

Sorted explicitly by (created_at, id) ascending -- NOT specified
anywhere in 03-api-contract.md, which is silent on ordering entirely;
this is a genuine implementation choice, not something derived from
the frozen contract, and shouldn't be mistaken for one. The reason it
exists at all isn't cosmetic: offset-based pagination is only correct
with a TOTAL ordering -- created_at alone doesn't guarantee one, since
two Jobs can share the same created_at (Python's stable sort would
then silently fall back to dict iteration order, which happens to be
deterministic in this in-memory implementation but isn't a guarantee
that survives a future database backend). id is included as an
explicit tie-breaker specifically to close that gap -- without it,
"deterministic ordering" would be a claim the implementation doesn't
actually keep. Which field and which direction is otherwise arbitrary
given the contract's silence -- ascending-by-created_at is a
reasonable default, not a considered product decision, and worth
revisiting if real usage (e.g. a dispatcher wanting newest-first)
suggests otherwise.
"""

from __future__ import annotations

from uuid import UUID

from app.exceptions.job import JobNotFoundError
from app.models.job import Job, JobStatus
from app.repositories.job_repository import JobPage


class InMemoryJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[UUID, Job] = {}

    async def create(self, job: Job) -> None:
        self._jobs[job.id] = job.model_copy(deep=True)

    async def get(self, tenant_id: UUID, job_id: UUID) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.tenant_id != tenant_id:
            return None
        return job.model_copy(deep=True)

    async def save(self, *, tenant_id: UUID, job: Job) -> Job:
        stored = self._jobs.get(job.id)

        if stored is None or stored.tenant_id != tenant_id:
            raise JobNotFoundError(job.id)

        if job.tenant_id != tenant_id:
            raise JobNotFoundError(job.id)

        self._jobs[job.id] = job.model_copy(deep=True)
        return job.model_copy(deep=True)

    async def list_by_tenant(
        self,
        *,
        tenant_id: UUID,
        status: JobStatus | None = None,
        client_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JobPage:
        matching = [
            job
            for job in self._jobs.values()
            if job.tenant_id == tenant_id
            and (status is None or job.status == status)
            and (client_id is None or job.client_id == client_id)
        ]
        matching.sort(key=lambda job: (job.created_at, str(job.id)))
        total = len(matching)
        page = matching[offset : offset + limit]
        return JobPage(items=[job.model_copy(deep=True) for job in page], total=total)
