"""
app/api/system/metrics.py

GET /metrics — Prometheus exposition (Platform Conventions §9).
Internal-network-only by convention, enforced at ingress/network
level, not application auth — this endpoint itself does not check any
permission or require authentication; gating it behind
Settings.METRICS_ENABLED (if ever needed) belongs in main.py's router
inclusion, not here, since main.py doesn't exist yet to make that call.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["system"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
