"""
app/api/system_metrics.py

Prometheus metrics endpoint. Actual collection happens in
app/middleware/metrics.py (MetricsMiddleware) — this route just
exposes whatever's been collected, in Prometheus's text exposition
format.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["system"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
