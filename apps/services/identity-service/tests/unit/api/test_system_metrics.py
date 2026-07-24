"""tests/unit/api/test_system_metrics.py

Tests for the Prometheus metrics endpoint and middleware.

Note: prometheus_client's default Counter/Histogram objects use ONE
shared global registry per process — module-level metric state
persists across every create_app() call within a single test run.
These tests deliberately check for the PRESENCE of a specific label
pattern in the output rather than an exact count, since exact counts
would be contaminated by whatever other tests ran earlier in the same
process.
"""


class TestMetricsEndpoint:
    def test_returns_prometheus_text_format(self, client):
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert "http_requests_total" in response.text


class TestRouteTemplateLabeling:
    def test_records_route_template_not_raw_path_value(self, client):
        """The critical cardinality-safety property: a request to a
        route with a path parameter must be recorded under the
        TEMPLATE (e.g. "/v1/tenants/{tenant_id}/invitations"), never
        the resolved path with a real UUID substituted in — see
        app/middleware/metrics.py's module docstring for why this
        matters. Using an unauthenticated request deliberately here —
        the middleware records the path regardless of whether the
        downstream handler succeeds or fails."""
        fake_tenant_id = "11111111-1111-1111-1111-111111111111"
        client.post(f"/v1/tenants/{fake_tenant_id}/invitations", json={})

        response = client.get("/metrics")
        body = response.text

        assert "/v1/tenants/{tenant_id}/invitations" in body
        assert fake_tenant_id not in body


class TestRecordsGenuinelyUnhandledExceptions:
    """In the real app, register_exception_handlers() includes a
    catch-all Exception handler — so a typical route-handler bug is
    already fully converted to a response before it would ever reach
    MetricsMiddleware's except branch (ExceptionMiddleware sits INSIDE
    user middleware, and finds that catch-all handler for virtually
    anything). This means the except branch mostly protects against
    exceptions in OTHER middleware sitting between MetricsMiddleware
    and the router, or bugs inside an exception handler itself — not
    "any route handler throws," which is already absorbed upstream.

    To actually exercise the except branch in isolation, this test
    uses a throwaway app with MetricsMiddleware installed but NO
    registered exception handlers at all, so a raised exception
    genuinely propagates past it, the same way an exception in a
    sibling middleware would in the real app."""

    def test_exception_escaping_past_metrics_is_still_recorded(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from prometheus_client.parser import text_string_to_metric_families

        from app.api.system_metrics import router as system_metrics_router
        from app.middleware.metrics import add_metrics_middleware

        app = FastAPI()
        add_metrics_middleware(app)
        app.include_router(system_metrics_router)

        @app.get("/boom")
        async def _boom():
            raise RuntimeError("simulated failure")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")
            assert response.status_code == 500

            metrics_response = client.get("/metrics")

        # Parsed, not string-matched — proves the same property without
        # depending on how prometheus_client happens to serialize label
        # order in the text exposition format.
        samples = [
            sample
            for family in text_string_to_metric_families(metrics_response.text)
            for sample in family.samples
        ]
        assert any(
            sample.name == "http_requests_total"
            and sample.labels
            == {"method": "GET", "path": "/boom", "status_code": "500"}
            for sample in samples
        )
