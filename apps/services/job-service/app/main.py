"""
app/main.py

Application factory for Job Service.

Production and tests build the same application through create_app().
Runtime service construction happens in the lifespan handler rather
than at import time.

A supplied ServiceRegistry is used directly, allowing integration tests
to inject application dependencies without monkeypatching
build_services().

TokenVerifier joins app.state this checkpoint -- deferred since Phase
0 specifically because job-service had no protected route yet; POST
/v1/jobs (landing next) is the first one. Stored as a separate, flat
app.state.token_verifier attribute, not part of ServiceRegistry --
matching client-service's own established distinction: it's a
security/auth concern, not a business-service concern. Constructed
unconditionally, every request: PyJWKClient fetches JWKS lazily and
caches, so construction itself performs no network I/O.
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
from app.security.token_verifier import TokenVerifier


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
        app.state.token_verifier = TokenVerifier(resolved_settings)
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
