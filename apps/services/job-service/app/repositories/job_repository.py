"""
app/repositories/in_memory/job_repository.py

InMemoryJobRepository -- the in-memory JobRepository implementation.
Ordinary dict-backed storage inside async method bodies -- no
asyncio.sleep, no executor, no fake concurrency. The async signatures
exist to match the platform-wide repository convention (see
app/repositories/job_repository.py's docstring), not because this
implementation performs any actual I/O.

Full aggregate isolation, both directions:
  - create()/save() store a deep copy of the given Job, so a caller
    mutating their own reference afterward cannot corrupt what's
    persisted.
  - get()/list_by_tenant()/save() return deep copies of stored Jobs,
    so a caller mutating what they got back cannot corrupt the
    repository's internal state either. Deep-copy-on-write alone
    doesn't guarantee this -- a caller handed a live reference to a
    stored object could still mutate it directly. All directions are
    tested explicitly.

Storage is keyed by job.id alone (not a composite tenant_id+id key).
get() and save() use tenant_id to validate ownership rather than to
locate the record: a job_id existing under a different tenant is
indistinguishable from one that does not exist at all, rather than
exposing a distinct "found but wrong tenant" case a caller could
probe for.

save()'s tenant check is deliberately two-part and does not trust the
provenance of the Job object it is handed:
  1. the currently stored record must belong to tenant_id;
  2. the Job being saved must itself claim tenant_id.
A missing record or either tenant mismatch raises JobNotFoundError.
The second check prevents a Job whose tenant_id was changed after it
was fetched from being used to move an aggregate between tenants.
Relying on every caller to have fetched and preserved the aggregate
correctly would weaken tenant isolation at the persistence boundary.

list_by_tenant() filters self._jobs.values() by tenant_id first
(mandatory, never optional), then by status/client_id when supplied,
computes total before slicing, and finally applies offset/limit.

Results are sorted explicitly by (created_at, id) ascending.
03-api-contract.md does not specify ordering, so this is an
implementation choice rather than part of the frozen API contract.
A total ordering is nevertheless required for reliable offset-based
pagination: created_at alone is insufficient because two Jobs can
share the same timestamp. id therefore acts as the deterministic
tie-breaker. The chosen fields and ascending direction can be
revisited if product requirements later prescribe another ordering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.models.job import Job, JobStatus


@dataclass
class JobPage:
    """Return shape for list_by_tenant() -- items plus the total count
    for the same filtered query."""

    items: list[Job]
    total: int


class JobRepository(Protocol):
    async def create(self, job: Job) -> None: ...

    async def get(self, tenant_id: UUID, job_id: UUID) -> Job | None: ...

    async def save(self, *, tenant_id: UUID, job: Job) -> Job:
        """Persist an update to an already-existing Job, scoped to
        tenant_id.

        Raises JobNotFoundError if no Job with job.id is currently
        stored, if the stored Job belongs to a different tenant, or if
        the supplied Job itself claims a different tenant_id from
        tenant_id. All three cases deliberately expose the same
        not-found result to preserve tenant non-disclosure.
        """
        ...

    async def list_by_tenant(
        self,
        *,
        tenant_id: UUID,
        status: JobStatus | None = None,
        client_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JobPage:
        """Filtered, paginated list for GET /v1/jobs.

        status and client_id are exact matches; 03-api-contract.md
        specifies no substring matching for either, unlike
        client-service's `name` filter on clients. limit and offset
        are already validated/clamped by the API layer before reaching
        this method.
        """
        ...
