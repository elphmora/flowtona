"""
app/repositories/job_repository.py

JobRepository -- Protocol for Job aggregate persistence, per Platform
Conventions §4. Current persistence surface: create(), get(), and
list_by_tenant(). No save(), update(), or delete() yet -- no command
built so far needs them.

Methods are async, matching the established platform-wide convention
(both identity-service's and client-service's requirements-dev.txt
state "Repository Protocol methods are async") -- an existing rule,
not something invented for job-service, and not deferred as
hypothetical future persistence.

get() takes tenant_id explicitly, not just job_id -- enforcing tenant
isolation at the repository layer itself, not solely trusting the
application layer to check job.tenant_id after the fact. A job_id
belonging to a different tenant returns None, indistinguishable from
not existing at all. create() needs no separate tenant_id parameter:
the Job object already carries its own (set by Job.create()), and
storing a fully-formed object has no cross-tenant retrieval risk the
way a bare-ID lookup does.

list_by_tenant() and JobPage deliberately mirror client-service's real,
confirmed ClientRepository.list_by_tenant()/ClientPage pattern exactly
-- same method name, same dataclass shape (items + total), same
reasoning: "both computed against the same filtered query -- not two
calls that could observe different snapshots under concurrent writes."
Consistency with the sibling service's already-solved pattern is worth
more than an independently "elegant" job-service convention. limit/
offset are expected already-validated/clamped by the API/schema layer
before reaching this method -- persistence code never owns HTTP/API
input policy, matching client-service's own Decision 7 precedent.
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

    async def list_by_tenant(
        self,
        *,
        tenant_id: UUID,
        status: JobStatus | None = None,
        client_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JobPage:
        """Filtered, paginated list -- GET /v1/jobs. status/client_id
        are exact matches (03-api-contract.md specifies no substring
        matching for either, unlike client-service's `name` filter on
        clients). limit/offset are already validated/clamped by the
        API schema layer before reaching this method."""
        ...
