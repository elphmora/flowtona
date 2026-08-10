"""
app/middleware/metrics.py

Records per-request Prometheus metrics — request count and latency,
labeled by method, route TEMPLATE (never a raw resolved path —
Platform Conventions §10: real client UUIDs as label values would
create unbounded cardinality), and status code.

Unmatched requests (no route matched at all) use a fixed sentinel,
"__unmatched__" — never the raw resolved path, which would otherwise
let an attacker generate unbounded unique label values.

http_requests_total only increments for a response that was actually
emitted; latency is still observed even when a request aborted before
emitting a response, since duration remains meaningful either way.

Does not increment `http_requests_total` for responses generated
entirely by Starlette's outer generic error handling (rather than by
one of this app's own registered exception handlers) — that response
is constructed outside this middleware's reach, so it's not counted
in http_requests_total (though its latency still is). See client-
service-architecture.md's Entity & Convention Clarifications for the
full reasoning and the Starlette internals this is derived from.
"""

import time

from fastapi import FastAPI
from prometheus_client import Counter, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_UNMATCHED_ROUTE = "__unmatched__"

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP responses actually emitted (never incremented for a "
    "request that aborted before any response started)",
    ["method", "route", "status_code"],
)
REQUEST_LATENCY_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds — observed even for requests "
    "that aborted before a response was emitted",
    ["method", "route"],
)


def _route_template(scope: Scope) -> str:
    """The matched route's TEMPLATE, read from scope["route"] — only
    populated after routing occurs, so must only be read after
    self.app(...) below has run. Falls back to _UNMATCHED_ROUTE, never
    the raw resolved path, when no route matched."""
    route = scope.get("route")
    if route is not None and hasattr(route, "path"):
        return str(route.path)
    return _UNMATCHED_ROUTE


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        start = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status_code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            route = _route_template(scope)
            status_code = status_holder.get("status_code")

            if status_code is not None:
                REQUEST_COUNT.labels(
                    method=method, route=route, status_code=str(status_code)
                ).inc()

            REQUEST_LATENCY_SECONDS.labels(method=method, route=route).observe(duration)


def add_metrics_middleware(app: FastAPI) -> None:
    app.add_middleware(MetricsMiddleware)
