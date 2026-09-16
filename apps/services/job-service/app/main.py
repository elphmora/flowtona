"""
app/main.py

Application factory for Job Service.

Production and tests build the same application through create_app().
Runtime service construction happens in the lifespan handler rather
than at import time.

build_services(resolved_settings) -- the call site changed alongside
app/api/dependencies.py's own signature change (that module's
docstring explains why: ClientServiceClient needs Settings fields to
construct, revisiting Phase 0's no-argument placeholder).

/v1/jobs joins the router list this checkpoint -- the first business
route, mounted under /v1 per Platform Conventions §9 (system routes
stay unversioned at the root; business routes are versioned).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import ServiceRegistry, build_services
from app.api.errors import register_exception_handlers
from app.api.system.health import router as health_router
from app.api.system.info import router as info_router
from app.api.system.metrics import router as metrics_router
from app.api.v1.jobs import router as jobs_router
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
        app.state.services = (
            registry if registry is not None else build_services(resolved_settings)
        )
        app.state.token_verifier = TokenVerifier(resolved_settings)
        yield

    app = FastAPI(
        title=resolved_settings.SERVICE_NAME,
        version=resolved_settings.SERVICE_VERSION,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Registered first -> innermost of the two custom middlewares
    # (closest to the router); metrics is the outer of the two.
    add_request_id_middleware(app)
    add_metrics_middleware(app)

    app.include_router(health_router)
    app.include_router(info_router)
    app.include_router(metrics_router)
    app.include_router(jobs_router, prefix="/v1")

    return app


app = create_app()
