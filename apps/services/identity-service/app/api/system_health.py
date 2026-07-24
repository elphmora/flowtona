"""
app/api/system_health.py

Kubernetes-facing health probes.

/healthz (liveness) — deliberately trivial, no downstream checks. A
liveness probe failure causes a pod RESTART, so it must never fail due
to a transient downstream issue; it only confirms the process is alive
and responding at all.

/readyz (readiness) and /startupz (startup) both perform the SAME real
check: attempting to build the JWKS response, which requires
TokenService to actually load the public key from disk. This is a
genuine, meaningful check — TokenService loads keys LAZILY (Phase 1
design), so the app can be "running" while still being unable to do
any JWT-related work if the signing keypair isn't actually available.
startupz and readyz deliberately share behavior here — this app's
startup is fast (in-memory construction, no slow I/O), so for a
fast-starting app "finished starting" and "ready to serve" are
effectively the same moment; there's no meaningful difference to
express between the two probes yet.
"""

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies import get_token_service
from app.services.token_service import TokenService

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _check_ready(token_service: TokenService) -> Response:
    try:
        await token_service.build_jwks()
    except Exception:
        # Deliberately broad — this endpoint's entire purpose is
        # converting ANY failure into a clear "not ready" signal for
        # k8s, not letting a specific exception type dictate the
        # response shape.
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(status_code=status.HTTP_200_OK)


@router.get("/readyz")
async def readyz(
    token_service: TokenService = Depends(get_token_service),
) -> Response:
    return await _check_ready(token_service)


@router.get("/startupz")
async def startupz(
    token_service: TokenService = Depends(get_token_service),
) -> Response:
    return await _check_ready(token_service)
