"""
app/repositories/job_repository.py

JobRepository -- Protocol for Job aggregate persistence, per Platform
Conventions §4. Phase 1 scope only: create() and get(). No save(),
update(), delete(), list(), or query/filter/pagination methods --
Phase 1's single command (Create Job) needs neither.

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
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.models.job import Job


class JobRepository(Protocol):
    async def create(self, job: Job) -> None: ...

    async def get(self, tenant_id: UUID, job_id: UUID) -> Job | None: ...
