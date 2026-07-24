"""
app/middleware/metrics.py

Automatically records HTTP-level Prometheus metrics for every request
— matches RequestIDMiddleware's "write once, benefits every route"
pattern, rather than manually instrumenting each route handler.

Business-specific counters (e.g. auth_login_success_total) are a
deliberate follow-up, not part of this first pass — this establishes
the foundational HTTP-level metrics every service needs without also
trying to decide the full set of business metrics in the same change.

CRITICAL correctness point: the `path` label uses the ROUTE TEMPLATE
(e.g. "/v1/tenants/{tenant_id}/invitations"), never the resolved path
with a real UUID substituted in. Using the raw path would create a
brand-new, permanent Prometheus time series for every distinct tenant
ID (or any other path parameter) ever seen — a well-known cardinality-
explosion bug that can genuinely degrade or crash a Prometheus
instance over time, since Prometheus stores a separate time series
per unique label combination.

Records status_code=500 for genuinely unhandled exceptions too, not
just handled application errors — call_next() is wrapped in try/except
specifically so an exception escaping all the way to Starlette's outer
ServerErrorMiddleware still gets recorded before being re-raised.
Without this, the metrics most worth having during an actual outage
(genuine unhandled failures) would be exactly the ones silently
missing.

TODO: BaseHTTPMiddleware (used here) has known Starlette limitations
around streaming responses and contextvars propagation; Starlette's
own docs recommend pure ASGI middleware for new implementations where
practical. This middleware is simple enough to translate almost
directly if that ever becomes necessary — worth revisiting if this
service introduces streaming responses or contextvars-based request
state, not urgent before then.
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)


def _route_template(request: Request) -> str:
    """The route's FULL TEMPLATE path (e.g.
    "/v1/tenants/{tenant_id}/invitations"), not the resolved path with
    a real UUID substituted in — see this module's docstring for why
    that distinction matters.

    Deliberately does NOT use request.scope["route"].path directly —
    that only returns the route's LOCALLY-defined pattern relative to
    whatever router it was registered on, not the full path including
    prefixes accumulated from parent routers it was later
    include_router()'d into (e.g. invites_router's own path has no
    "/v1" prefix; that's added when it's included into v1_router).
    Using the bare local path would make routes under different
    version prefixes indistinguishable in Prometheus.

    Instead, reconstructs the full template by substituting each
    resolved path parameter's ACTUAL value back into the FULL resolved
    URL, using request.scope["path_params"] (populated once routing
    completes). This works correctly regardless of router nesting
    depth, since it operates on the real, complete URL string rather
    than trying to track prefixes through the router hierarchy.

    Must be called AFTER routing has had a chance to occur — i.e.
    after call_next() returns or raises, never before."""
    route = request.scope.get("route")
    if route is None:
        return request.url.path

    template = request.url.path
    path_params: dict[str, object] = request.scope.get("path_params", {})
    for name, value in path_params.items():
        template = template.replace(str(value), f"{{{name}}}", 1)
    return template


def _record(
    *, method: str, path: str, status_code: int, duration_seconds: float
) -> None:
    REQUEST_COUNT.labels(method=method, path=path, status_code=status_code).inc()
    REQUEST_DURATION.labels(method=method, path=path).observe(duration_seconds)


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            _record(
                method=request.method,
                path=_route_template(request),
                status_code=500,
                duration_seconds=time.perf_counter() - start,
            )
            raise

        _record(
            method=request.method,
            path=_route_template(request),
            status_code=response.status_code,
            duration_seconds=time.perf_counter() - start,
        )
        return response


def add_metrics_middleware(app: FastAPI) -> None:
    app.add_middleware(MetricsMiddleware)
