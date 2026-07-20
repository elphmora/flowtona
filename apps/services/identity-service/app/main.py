"""
app/main.py

Application entrypoint — assembles the FastAPI app from its
constituent pieces (middleware, exception handlers, dependency-injected
services, routes). Kept deliberately small and just wiring; no
business logic here.

No routes registered yet — this is the service-wiring infrastructure
piece. Route registration is the next piece of work; this service is
not yet runnable as a meaningful API (see the operator guide's
"Running locally" section).

Middleware and exception handlers are registered in this specific
order: request ID middleware FIRST, so request.state.request_id
already exists by the time any exception handler runs and needs it.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import build_auth_service
from app.api.errors import register_exception_handlers
from app.core.config import settings
from app.middleware.request_id import add_request_id_middleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Constructs the entire service graph ONCE at startup (see
    app/api/dependencies.py's build_auth_service()) and attaches it to
    app.state, where route dependencies (get_auth_service) read it
    from. Also attaches settings itself — future health/diagnostics/
    version endpoints will want configuration information without
    each needing its own import. No teardown needed yet — the in-
    memory store is simply garbage collected when the process exits;
    this will need real cleanup once Phase 2 introduces persistent
    connections."""
    app.state.settings = settings
    app.state.auth_service = build_auth_service(settings)
    yield


app = FastAPI(
    title=settings.SERVICE_NAME,
    version=settings.SERVICE_VERSION,
    lifespan=lifespan,
)

add_request_id_middleware(app)
register_exception_handlers(app)
