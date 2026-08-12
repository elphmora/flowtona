"""
app/main.py

create_app(settings=None, *, registry=None) factory (Platform
Conventions: "production and tests build the literal same app — never
a hand-assembled test duplicate"). Service construction happens in a
lifespan handler, not at import time.

Injectable-registry rule:
    registry supplied  -> lifespan uses it directly.
    registry is None   -> lifespan builds a new ServiceRegistry via
                           build_services(), which takes no settings
                           parameter today (see app/api/dependencies.py
                           for why) — documenting today's actual
                           signature, not a hypothetical one.
This preserves dependency injection for tests without needing to
monkeypatch build_services() — a test can construct its own
ServiceRegistry (e.g. with pre-seeded repository state) and hand it to
create_app() directly. The whole registry is stored as a single
app.state.services attribute, not unpacked into three flat app.state
attributes — preserves the grouping ServiceRegistry already
represents (see app/api/dependencies.py) rather than discarding it the
moment it reaches app.state. TokenVerifier stays a separate, flat
app.state.token_verifier attribute — it isn't part of that grouping
(see app/api/dependencies.py's own docstring for why).

TokenVerifier has no equivalent injection seam (yet, deliberately not
built ahead of a need): PyJWKClient fetches JWKS lazily and caches, so
merely constructing TokenVerifier(settings) here performs no network
I/O — safe to construct unconditionally even when identity-service
isn't reachable, as long as no test actually exercises a route that
triggers real JWT verification against it. Add an injection seam if
that stops being true, not before.

Middleware registration order is deliberate, not accidental insertion
order: RequestIDMiddleware is registered first, MetricsMiddleware
second, making MetricsMiddleware the outer of the two custom layers.
This lets request metrics cover request-ID processing as well as
routing, handled exceptions, and endpoint execution — the widest
custom/application-level measurement scope available to these two
middlewares. It does NOT claim to wrap Starlette's own outer
ServerErrorMiddleware: a response built entirely by Starlette's
generic error handling (as opposed to one of this app's own registered
exception handlers) is constructed outside both middlewares' reach
regardless of their relative order — see client-service-architecture.md
for the full reasoning.

System routers (health, info, metrics) mount at the unversioned root,
per Platform Conventions §9. Business routers mount under /v1 —
clients (feature/client-service-clients-api) is the first; sites and
contacts follow in their own branches once built, not added here
speculatively ahead of them.

Integration tests using create_app() must use TestClient as a context
manager for the lifespan handler to execute:
    with TestClient(app) as client:
        ...
not bare TestClient(app) — otherwise app.state.services and
app.state.token_verifier are never populated and every dependency
provider fails. See tests/integration/test_main.py.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.dependencies import ServiceRegistry, build_services
from app.api.errors import register_exception_handlers
from app.api.system.health import router as health_router
from app.api.system.info import router as info_router
from app.api.system.metrics import router as metrics_router
from app.api.v1.clients import router as clients_router
from app.api.v1.sites import router as sites_router
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
        app.state.services = registry or build_services()
        app.state.token_verifier = TokenVerifier(resolved_settings)
        yield

    app = FastAPI(
        title=resolved_settings.SERVICE_NAME,
        version=resolved_settings.SERVICE_VERSION,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Deliberate order — see module docstring.
    add_request_id_middleware(app)
    add_metrics_middleware(app)

    app.include_router(health_router)
    app.include_router(info_router)
    app.include_router(clients_router)
    app.include_router(sites_router)
    if resolved_settings.METRICS_ENABLED:
        app.include_router(metrics_router)

    return app
