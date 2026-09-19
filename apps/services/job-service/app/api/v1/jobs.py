"""
app/api/v1/jobs.py

POST /v1/jobs -- Create Job, per 03-api-contract.md and
01-create-job.md's sequence diagram.

Permission pre-check, exactly as the diagram specifies: BOTH
jobs:write AND clients:read are checked, before any network call is
made -- Job Service's own fail-fast pre-check (Platform Conventions
§11 Amendment 7), not a substitute for Client Service's own
independent re-verification of the forwarded token. Both
require_permission(...) dependencies resolve through the same
underlying get_current_claims dependency, which FastAPI caches per
request -- JWT verification happens exactly once per request,
regardless of how many require_permission(...) checks are stacked on
this route.

access_token comes from get_access_token(), not from AccessTokenClaims
-- deliberately: AccessTokenClaims stays a clean, verified abstraction,
never contaminated with the raw, unverified credential. get_access_token
establishes its own required-str guarantee independently (see
app/api/auth_dependency.py's docstring) -- no assertion, no implicit
reliance on another dependency's resolution order.

changed_by / sub is NOT extracted or threaded through -- Job.create()
has no such parameter, and 03-api-contract.md's Create Job response
has no created_by field (see app/models/job.py's own docstring for the
full Decision 4 reasoning).

Query Operations checkpoint (GET routes below) -- all three require
jobs:read only, confirmed directly from 03-api-contract.md: unlike
Create Job, no clients:read and no outbound Client Service call for
any Query Operation.

limit/offset validation mirrors client-service's own established
pattern exactly: Query(ge=1)/Query(ge=0) REJECTS a malformed value
(0, negative) with 422; a limit ABOVE the max is silently CLAMPED, not
rejected -- two different kinds of problem, handled differently
(03-api-contract.md: "default 20, max 100, clamped").

Phase 2 introduces the real Visit domain model. get_visit() therefore
translates the returned Visit explicitly through
VisitResponse.from_domain(), preserving the domain/API boundary used
by JobResponse. The response schema itself is unchanged from the
frozen 03-api-contract.md shape established during Query Operations.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.auth_dependency import get_access_token
from app.api.dependencies import get_job_service
from app.api.permission_dependency import require_permission
from app.api.schemas.job import (
    CreateJobRequest,
    JobListItemResponse,
    JobListResponse,
    JobResponse,
    VisitResponse,
)
from app.constants.permissions import CLIENTS_READ, JOBS_READ, JOBS_WRITE
from app.models.job import JobStatus
from app.security.token_verifier import AccessTokenClaims
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])

_MAX_LIMIT = 100


@router.post("", status_code=201)
async def create_job(
    body: CreateJobRequest,
    access_token: Annotated[str, Depends(get_access_token)],
    claims: Annotated[AccessTokenClaims, Depends(require_permission(JOBS_WRITE))],
    _clients_read_claims: Annotated[
        AccessTokenClaims, Depends(require_permission(CLIENTS_READ))
    ],
    job_service: Annotated[JobService, Depends(get_job_service)],
) -> JobResponse:
    job = await job_service.create_job(
        tenant_id=claims.tenant_id,
        access_token=access_token,
        client_id=body.client_id,
        site_id=body.site_id,
        contact_id=body.contact_id,
        title=body.title,
        description=body.description,
    )
    return JobResponse.from_domain(job)


@router.get("")
async def list_jobs(
    claims: Annotated[AccessTokenClaims, Depends(require_permission(JOBS_READ))],
    job_service: Annotated[JobService, Depends(get_job_service)],
    status: JobStatus | None = None,
    client_id: UUID | None = None,
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    clamped_limit = min(limit, _MAX_LIMIT)

    page = await job_service.list_jobs(
        tenant_id=claims.tenant_id,
        status=status,
        client_id=client_id,
        limit=clamped_limit,
        offset=offset,
    )

    return JobListResponse(
        items=[JobListItemResponse.from_domain(job) for job in page.items],
        total=page.total,
        limit=clamped_limit,
        offset=offset,
    )


@router.get("/{job_id}")
async def get_job(
    job_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(JOBS_READ))],
    job_service: Annotated[JobService, Depends(get_job_service)],
) -> JobResponse:
    job = await job_service.get_job(tenant_id=claims.tenant_id, job_id=job_id)
    return JobResponse.from_domain(job)


@router.get("/{job_id}/visits/{visit_id}")
async def get_visit(
    job_id: UUID,
    visit_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(JOBS_READ))],
    job_service: Annotated[JobService, Depends(get_job_service)],
) -> VisitResponse:
    visit = await job_service.get_visit(
        tenant_id=claims.tenant_id, job_id=job_id, visit_id=visit_id
    )
    return VisitResponse.from_domain(visit)
