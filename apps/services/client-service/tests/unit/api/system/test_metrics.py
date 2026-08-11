"""
tests/unit/api/system/test_metrics.py
"""


class TestMetrics:
    def test_returns_200(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_content_type_is_prometheus_exposition_format(self, client):
        response = client.get("/metrics")
        assert "text/plain" in response.headers["content-type"]

    def test_exposes_real_middleware_recorded_data(self, client):
        """Not just proving the endpoint returns 200 — proving it
        actually serves what app/middleware/metrics.py recorded. Hits
        a real route first (which the shared test app's own
        MetricsMiddleware observes), then confirms that observation
        appears in the /metrics response body."""
        client.get("/healthz")

        response = client.get("/metrics")

        assert "http_requests_total" in response.text
        assert 'route="/healthz"' in response.text

    def test_does_not_require_authentication(self, client):
        """Platform Conventions §9: /metrics access is restricted at
        the ingress/network level, not application auth — confirms no
        Authorization header is required to reach it."""
        response = client.get("/metrics")
        assert response.status_code == 200
