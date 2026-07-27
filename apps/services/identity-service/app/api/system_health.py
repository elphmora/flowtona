"""
app/api/system_health.py

Kubernetes-facing health probes.

/healthz (liveness) — deliberately trivial, no downstream checks. A
liveness probe failure causes a pod RESTART, so it must never fail due
to a transient downstream issue; it only confirms the process is alive
and responding at all.

/readyz (readiness) and /startupz (startup) share the SAME underlying
check (see _check_ready()'s own docstring) but return DIFFERENT status
values — "ready"/"not_ready" only ever come from /readyz,
"started"/"not_started" only ever come from /startupz. That alone
makes a response body unambiguous about which probe produced it,
without needing a separate field naming the probe explicitly.

Same implementation, different semantic meaning: this app's startup is
fast (in-memory construction, no slow I/O), so "finished starting" and
"ready to serve" are genuinely the same moment today. That's expected
to change once Phase 2 introduces real dependencies (e.g. a database
connection) — at that point /startupz might stay a simple "did the
process initialize" check while /readyz additionally verifies those
dependencies are reachable.
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.dependencies import get_token_service
from app.services.token_service import TokenService

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _check_ready(
    token_service: TokenService,
    *,
    ready_status: str,
    not_ready_status: str,
) -> JSONResponse:
    """Shared readiness/startup implementation.

    Both probes currently verify the application's ability to load the
    configured JWT signing keypair, by attempting to construct the
    JWKS response. TokenService loads keys LAZILY (Phase 1 design), so
    the app can be "running" while still being unable to do any
    JWT-related work if the signing keypair isn't actually available —
    this check catches that condition specifically.

    Any failure is converted into a 503 response using the caller-
    specific failure status, without exposing internal failure details
    to callers — an operator diagnosing this should look at server-side
    logs, not have internal failure detail exposed over an
    unauthenticated endpoint.

    `ready_status` and `not_ready_status` let each caller (readyz,
    startupz) share this exact check while returning a response
    payload that reflects its own semantic meaning, not a generic one
    that doesn't say which probe was actually hit."""
    try:
        await token_service.build_jwks()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": not_ready_status},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": ready_status},
    )


@router.get("/readyz")
async def readyz(
    token_service: TokenService = Depends(get_token_service),
) -> JSONResponse:
    return await _check_ready(
        token_service,
        ready_status="ready",
        not_ready_status="not_ready",
    )


@router.get("/startupz")
async def startupz(
    token_service: TokenService = Depends(get_token_service),
) -> JSONResponse:
    return await _check_ready(
        token_service,
        ready_status="started",
        not_ready_status="not_started",
    )
