"""
app/api/system/health.py

Kubernetes-facing health probes. Response bodies follow the frozen
platform-conventions.md Amendment 6 contract exactly.

/healthz (liveness) — deliberately trivial, no downstream checks. A
liveness probe failure causes a pod RESTART, so it must never fail due
to a transient downstream issue.

/readyz (readiness) and /startupz (startup) are separate route
functions, never a shared decision function, per Amendment 6's
explicit rule. Phase 0/1: both succeed unconditionally — Job Service
has no readiness-critical dependency yet. A real check is introduced
only when persistence lands.
"""

from fastapi import APIRouter, Response, status

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {
        "probe": "health",
        "status": "ok",
    }


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, str]:
    response.status_code = status.HTTP_200_OK
    return {
        "probe": "readiness",
        "status": "ready",
    }


@router.get("/startupz")
async def startupz(response: Response) -> dict[str, str]:
    response.status_code = status.HTTP_200_OK
    return {
        "probe": "startup",
        "status": "started",
    }
