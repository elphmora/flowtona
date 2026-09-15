"""
app/repositories/in_memory/job_repository.py

InMemoryJobRepository -- Phase 1's only JobRepository implementation.
Ordinary dict-backed storage inside async method bodies -- no
asyncio.sleep, no executor, no fake concurrency. The async signatures
exist to match the platform-wide repository convention (see
app/repositories/job_repository.py's docstring), not because this
implementation performs any actual I/O.

Full aggregate isolation, both directions:
  - create() stores a deep copy of the given Job, so a caller mutating
    their own reference after calling create() cannot corrupt what's
    persisted.
  - get() returns a deep copy of the stored Job, so a caller mutating
    what they got back cannot corrupt the repository's internal state
    either. Deep-copy-on-write alone doesn't guarantee this -- a
    caller handed a live reference to the stored object could still
    mutate it directly. Both directions are tested explicitly.

Storage keyed by job.id alone (not a composite tenant_id+id key) --
get()'s tenant_id parameter VALIDATES the match rather than locating
the record: a job_id existing under a different tenant returns None,
exactly as if it didn't exist, rather than a distinct "found but wrong
tenant" case a caller could probe for.
"""

from __future__ import annotations

from uuid import UUID

from app.models.job import Job


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
