"""
app/main.py

Application factory and entrypoint. create_app() assembles the FastAPI
app from its constituent pieces (middleware, exception handlers,
routes, service wiring) — extracted as a function, not left as
module-level statements, specifically so tests build the SAME real
application every request actually runs through, rather than a hand-
assembled duplicate that risks silently diverging as this file grows
(CORS, compression, tracing, metrics, more middleware — all of which
a test-only reassembly would need to remember to duplicate and keep
in sync).

Account-entry routes (signup, login, select-tenant) are registered via
app/api/v1/router.py. Remaining routes (sessions, verification,
invitations) are added incrementally in their own PRs, alongside
AuthService's own build order.

Middleware and exception handlers are registered in this specific
order: request ID middleware FIRST, so request.state.request_id
already exists by the time any exception handler runs and needs it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import ServiceRegistry, build_services
from app.api.errors import register_exception_handlers
from app.api.v1.router import router as v1_router
from app.core.config import Settings
from app.core.config import settings as default_settings
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
        by the Bearer-token auth dependency). Also attaches settings
        itself — future health/diagnostics/version endpoints will want
        configuration information without each needing its own import.
        No teardown needed yet — the in-memory store is simply garbage
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
    register_exception_handlers(app)
    app.include_router(v1_router)

    return app


app = create_app()
