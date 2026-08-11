"""
tests/integration/test_main.py

Platform Conventions §8's actual "integration" tier: the real
create_app() instance (not a hand-assembled throwaway app), a real
TestClient, real in-memory repositories. First genuine occupant of
tests/integration/ in this codebase — nothing belonged here before
main.py existed to test (Amendment 5 reserved the name; this is what
it was reserved for).

FastAPI/Starlette only run lifespan handlers when TestClient is used
as a context manager (`with TestClient(app) as client:`), not bare
`TestClient(app)` — every test below uses the context-manager form for
exactly this reason; app.state.client_service etc. would otherwise
never be populated and every dependency provider would fail.
"""

from fastapi.testclient import TestClient

from app.api.dependencies import build_services
from app.core.config import Settings
from app.main import create_app


class TestCreateAppLifespan:
    def test_service_registry_populated_on_app_state(self):
        app = create_app()
        with TestClient(app):
            assert app.state.services.client_service is not None
            assert app.state.services.site_service is not None
            assert app.state.services.contact_service is not None

    def test_token_verifier_populated_on_app_state(self):
        app = create_app()
        with TestClient(app):
            assert app.state.token_verifier is not None

    def test_default_settings_used_when_none_provided(self):
        """Constructing TokenVerifier(Settings()) performs no network
        I/O — PyJWKClient fetches lazily — so this proves the
        no-args path doesn't crash at construction time, not that
        verification itself works against real settings."""
        app = create_app()
        with TestClient(app):
            assert app.state.token_verifier is not None


class TestInjectableRegistry:
    def test_supplied_registry_is_used_directly(self):
        """Proves the injectable-registry rule actually works: a
        registry passed to create_app() ends up on app.state
        UNCHANGED — not rebuilt via build_services(), not copied, the
        literal same object."""
        injected_registry = build_services()
        app = create_app(registry=injected_registry)

        with TestClient(app):
            assert app.state.services is injected_registry

    def test_none_registry_builds_a_fresh_one(self):
        """The other half of the rule: registry=None (the default)
        must not silently reuse some other call's registry — each
        create_app() call without an explicit registry gets its own,
        independently built ServiceRegistry."""
        app_one = create_app()
        app_two = create_app()

        with TestClient(app_one), TestClient(app_two):
            assert app_one.state.services is not app_two.state.services


class TestRealHTTPRoundTrip:
    """Full stack, for real: middleware, routing, dependency
    injection, all through the actual application — not a throwaway
    test app standing in for it. Response body contracts are covered
    by TestProbeResponseContracts below; these tests are about
    cross-cutting behavior (request-ID propagation, metrics recording)
    that spans more than one endpoint."""

    def test_request_id_header_present_on_real_response(self):
        """Proves the middleware is actually registered and running
        inside the real app, not just present in isolated middleware
        tests against a throwaway one."""
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/healthz")
            assert "x-request-id" in response.headers

    def test_metrics_records_real_requests(self):
        """The same proof test_exposes_real_middleware_recorded_data
        gave for the throwaway app, now against the real one: proves
        MetricsMiddleware actually observes a request through
        create_app()'s real router, and /metrics actually exposes it."""
        app = create_app()
        with TestClient(app) as client:
            client.get("/healthz")
            response = client.get("/metrics")
            assert "http_requests_total" in response.text


class TestMetricsGating:
    def test_metrics_route_absent_when_disabled(self):
        """METRICS_ENABLED=False must mean /metrics isn't part of the
        application surface at all — a 404, not a 200 with some
        disabled-state body."""
        settings = Settings(METRICS_ENABLED=False)
        app = create_app(settings=settings)

        with TestClient(app) as client:
            response = client.get("/metrics")
            assert response.status_code == 404

    def test_metrics_route_present_when_enabled(self):
        settings = Settings(METRICS_ENABLED=True)
        app = create_app(settings=settings)

        with TestClient(app) as client:
            response = client.get("/metrics")
            assert response.status_code == 200


class TestAllOperationalEndpointsRegistered:
    """Confirms every Platform Conventions §9 endpoint is actually
    reachable through the real app — registration only, not response
    contracts (those are covered separately below, where the JSON body
    itself matters, not just that the route exists)."""

    def test_all_endpoints_return_200(self):
        with TestClient(create_app()) as client:
            for path in ("/healthz", "/readyz", "/startupz", "/info", "/metrics"):
                response = client.get(path)
                assert response.status_code == 200, path


class TestProbeResponseContracts:
    """Response BODIES, not just that the routes exist — these are
    contracts other tooling depends on (Platform Conventions §9
    Amendment 6), worth their own dedicated assertions."""

    def test_healthz_contract(self):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/healthz")
            assert response.json() == {"probe": "health", "status": "ok"}

    def test_readyz_contract(self):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/readyz")
            assert response.json() == {"probe": "readiness", "status": "ready"}

    def test_startupz_contract(self):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/startupz")
            assert response.json() == {"probe": "startup", "status": "started"}

    def test_info_contract(self):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/info")
            assert set(response.json().keys()) == {
                "service",
                "version",
                "build",
                "git_sha",
                "environment",
            }

    def test_metrics_content_type(self):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/metrics")
            assert "text/plain" in response.headers["content-type"]
