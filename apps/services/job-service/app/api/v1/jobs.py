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
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.auth_dependency import get_access_token
from app.api.dependencies import get_job_service
from app.api.permission_dependency import require_permission
from app.api.schemas.job import CreateJobRequest, JobResponse
from app.constants.permissions import CLIENTS_READ, JOBS_WRITE
from app.security.token_verifier import AccessTokenClaims
from app.services.job_service import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
