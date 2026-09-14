"""
app/api/system/metrics.py

GET /metrics — Prometheus exposition, per Platform Conventions §9/§10.
Internal-network-only by convention (enforced at ingress/network
level, not application auth). Unconditionally registered — no feature
flag; see app/main.py's docstring for why an earlier draft's flag was
removed rather than wired up.

Reads from app/metrics/registry.py's re-exported default global
REGISTRY — the same one app/middleware/metrics.py's counters register
into automatically, closing the split-registry risk a dedicated
CollectorRegistry() would have silently introduced.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.metrics.registry import REGISTRY

router = APIRouter(tags=["system"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
