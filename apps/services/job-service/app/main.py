"""
app/main.py

Application factory for Job Service.

Production and tests build the same application through create_app().
Runtime service construction happens in the lifespan handler rather
than at import time.

A supplied ServiceRegistry is used directly, allowing integration tests
to inject application dependencies without monkeypatching
build_services(). `registry if registry is not None else
build_services()` is used deliberately instead of `registry or
build_services()` — this is dependency injection, not a truthiness
check, and an explicitly-supplied-but-falsy registry (not possible
today with an empty dataclass, but a real risk once ServiceRegistry
grows fields) should never be silently discarded.

The resolved Settings instance is stored on app.state.settings
alongside app.state.services. This closes a real bug: /info previously
constructed its own fresh Settings() independently of whatever settings
create_app() was actually given, so a test supplying a custom Settings
instance to create_app(settings=...) would see FastAPI's own title/
version reflect it while GET /info silently reported different
(default) values. There is now exactly one resolved runtime
configuration object, read by every route that needs it.

Phase 0 exposes only unversioned operational endpoints, unconditionally
— no feature flag gates /metrics in this phase; that was a leftover
from a draft that never actually defined the flag it referenced, which
would have raised AttributeError on the first request. Business
routes, JWT verification, permission dependencies and Client Service
integration arrive with the Phase 1 Create Job vertical slice.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import ServiceRegistry, build_services
from app.api.errors import register_exception_handlers
from app.api.system.health import router as health_router
from app.api.system.info import router as info_router
from app.api.system.metrics import router as metrics_router
from app.core.config import Settings
from app.middleware.metrics import add_metrics_middleware
from app.middleware.request_id import add_request_id_middleware


def create_app(
    settings: Settings | None = None,
    *,
    registry: ServiceRegistry | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved_settings
        app.state.services = registry if registry is not None else build_services()
        yield

    app = FastAPI(
        title=resolved_settings.SERVICE_NAME,
        version=resolved_settings.SERVICE_VERSION,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Registered first -> innermost of the two custom middlewares
    # (closest to the router); metrics is the outer of the two. See
    # app/middleware/request_id.py's own docstring for the full
    # reasoning behind this ordering.
    add_request_id_middleware(app)
    add_metrics_middleware(app)

    app.include_router(health_router)
    app.include_router(info_router)
    app.include_router(metrics_router)

    # Phase 1 onward: app.include_router(jobs_router, prefix="/v1")

    return app


app = create_app()
