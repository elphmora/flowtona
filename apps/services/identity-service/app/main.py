"""
app/main.py

Application factory and entrypoint. create_app() assembles the FastAPI
app from its constituent pieces (middleware, exception handlers,
routes, service wiring) — extracted as a function, not left as
module-level statements, specifically so tests build the SAME real
application every request actually runs through, rather than a hand-
assembled duplicate that risks silently diverging as this file grows.

app/api/v1/router.py registers the versioned business API (auth,
invitations, and whatever follows). System endpoints (health probes,
metadata, metrics) are registered directly here, unversioned — they're
infrastructure concerns consumed by k8s/Prometheus, not part of the
API surface a client would care about versioning.

Middleware registration order: Starlette wraps middleware in REVERSE
of registration order (the last one added ends up outermost, running
first on the way in) — so request ID and metrics middleware here do
NOT run in the order they're registered in. This doesn't matter
between these two specifically: MetricsMiddleware never reads
request.state.request_id, so there's no dependency between them either
way. The property that DOES matter — request.state.request_id existing
before the RFC 9457 exception handlers read it — holds regardless of
this ordering, since FastAPI's exception-handling machinery
(ExceptionMiddleware) is always innermost relative to every user
middleware, no matter what order they were added in. Verified by
tests/unit/api/test_middleware_ordering.py, not just asserted here.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import ServiceRegistry, build_services
from app.api.errors import register_exception_handlers
from app.api.system_health import router as system_health_router
from app.api.system_meta import router as system_meta_router
from app.api.system_metrics import router as system_metrics_router
from app.api.v1.router import router as v1_router
from app.core.config import Settings
from app.core.config import settings as default_settings
from app.middleware.metrics import add_metrics_middleware
from app.middleware.request_id import add_request_id_middleware


def create_app(
    settings: Settings | None = None, *, registry: ServiceRegistry | None = None
) -> FastAPI:
    """Build a fully-assembled FastAPI app.

    `settings` defaults to the global settings singleton — production
    just calls create_app() with no arguments. Tests override it (e.g.
    a tmp_path-based SECRETS_DIR) by passing their own Settings
    instance.

    `registry` is normally left as None — production builds the service
    graph during application startup (once per process, via the
    lifespan handler below, not per request). Tests that need DIRECT
    access to the SAME service graph the app's routes use (e.g. seeding
    extra state via registry.membership_service.create(...) before
    making an HTTP call) pass an already-built ServiceRegistry instead
    — this guarantees the object graph a test manipulates directly is
    the exact one the app's routes are using, not a second, disconnected
    copy from calling build_services() twice."""
    app_settings = settings if settings is not None else default_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Constructs the service graph ONCE at startup (or reuses the
        one passed in) and attaches the pieces route dependencies
        actually need to app.state — auth_service for
        get_auth_service(), token_service for get_token_service() (used
        by the Bearer-token auth dependency and the health/metadata
        endpoints). Also attaches settings itself, used by /info. No
        teardown needed yet — the in-memory store is simply garbage
        collected when the process exits; this will need real cleanup
        once Phase 2 introduces persistent connections."""
        resolved_registry = (
            registry if registry is not None else build_services(app_settings)
        )
        app.state.settings = app_settings
        app.state.auth_service = resolved_registry.auth_service
        app.state.token_service = resolved_registry.token_service
        yield

    app = FastAPI(
        title=app_settings.SERVICE_NAME,
        version=app_settings.SERVICE_VERSION,
        lifespan=lifespan,
    )

    add_request_id_middleware(app)
    add_metrics_middleware(app)
    register_exception_handlers(app)
    app.include_router(v1_router)
    app.include_router(system_health_router)
    app.include_router(system_meta_router)
    app.include_router(system_metrics_router)

    return app


app = create_app()
