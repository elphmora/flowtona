"""
app/api/system/health.py

Liveness, readiness, and startup probes. Response shape follows
Platform Conventions §9 (Amendment 6).

healthz   -> process is alive
readyz    -> instance is ready to receive traffic
startupz  -> application startup has completed

Client-service currently has no external dependency requiring a
readiness or startup check, so both probes return success. Readiness
and startup are independent operational concepts, and the
implementation preserves that independence even though both currently
return success — see readyz()/startupz() below.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"probe": "health", "status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """No real readiness check exists yet — see module docstring."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"probe": "readiness", "status": "ready"},
    )


@router.get("/startupz")
async def startupz() -> JSONResponse:
    """No real startup check exists yet — see module docstring."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"probe": "startup", "status": "started"},
    )
