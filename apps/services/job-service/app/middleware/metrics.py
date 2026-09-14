"""
app/middleware/metrics.py

Pure ASGI, matching app/middleware/request_id.py's own reasoning.
Registered second in app/main.py -> outer of the two custom
middlewares, so request timing includes RequestIDMiddleware's own
(negligible) overhead as well as routing, handled exceptions, and
endpoint execution.

Metric recording happens in a `finally` block, not after a plain
`await self.app(...)` call. Without it, if the inner app raises (a
genuinely uncaught exception, converted into a 500 by Starlette's
outer ServerErrorMiddleware, which sits OUTSIDE this middleware -- see
app/api/errors.py's docstring), execution would never reach the metric
calls, and the exact requests most worth seeing in HTTP metrics
(server errors) would silently vanish from them. On that path,
`status_code_holder` was never populated (the response never started),
so the status is recorded as 500 deliberately -- not 0, not dropped --
since that's the accurate operational outcome for this codebase's
error handling.

Route-template extraction, corrected after a real test failure: an
earlier version of this file re-implemented route matching itself
(iterating app.routes and calling route.matches(scope) independently),
which is exactly the kind of thing that's easy to get subtly wrong
re-deriving from outside the routing system, and did in fact produce
wrong results at runtime (/healthz was being recorded as
"__unmatched__"). This version instead reads `scope["route"]` directly
-- Starlette's own Router sets this key as a side effect of actually
dispatching the request, so by the time this middleware's `finally`
block runs (after `self.app(...)` has fully executed, having gone
through real routing), scope["route"] reliably reflects whatever
Starlette's routing genuinely decided, rather than a second,
independently-computed opinion that can disagree with it. This is the
standard technique used by real FastAPI/Prometheus integrations, not
a novel approach.

Cardinality-safe per Platform Conventions §10: route TEMPLATE labels
(e.g. "/healthz", later "/v1/jobs/{job_id}"), never raw resolved paths
or any unbounded value. An unmatched route (no "route" key in scope --
a genuine 404, nothing in the app matched) collapses to the sentinel
"__unmatched__", matching client-service's own documented convention
for the same situation.
"""

from __future__ import annotations

import time
from collections.abc import MutableMapping
from typing import Any

from fastapi import FastAPI
from prometheus_client import Counter, Histogram
from starlette.types import ASGIApp, Receive, Scope, Send

UNMATCHED_ROUTE_LABEL = "__unmatched__"

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests received.",
    labelnames=("method", "route", "status_code"),
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    labelnames=("method", "route"),
)


def _route_template(scope: Scope) -> str:
    """Route-template extraction via Starlette's own scope["route"]
    side effect, collapsing to a bounded sentinel when nothing matched
    (Platform Conventions §10). See module docstring for why this
    replaced an earlier, independently-re-matching implementation."""
    route = scope.get("route")
    if route is not None:
        path: str | None = getattr(route, "path", None)
        if path:
            return path
    return UNMATCHED_ROUTE_LABEL


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        start = time.perf_counter()
        status_code_holder: dict[str, int] = {}

        async def send_with_timing(message: MutableMapping[str, Any]) -> None:
            # Typed as MutableMapping[str, Any], not bare dict -- see
            # app/middleware/request_id.py's equivalent comment for why.
            if message["type"] == "http.response.start":
                status_code_holder["status_code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_timing)
        finally:
            duration = time.perf_counter() - start
            route = _route_template(scope)
            # No response ever started -> the inner app raised past
            # every registered handler, all the way to Starlette's
            # outer ServerErrorMiddleware. 500 is the accurate outcome
            # for this codebase's error handling, not a guess.
            status_code = status_code_holder.get("status_code", 500)

            HTTP_REQUESTS_TOTAL.labels(
                method=method, route=route, status_code=str(status_code)
            ).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(
                duration
            )


def add_metrics_middleware(app: FastAPI) -> None:
    app.add_middleware(MetricsMiddleware)
