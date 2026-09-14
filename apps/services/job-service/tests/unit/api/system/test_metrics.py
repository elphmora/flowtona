"""
tests/unit/api/system/test_metrics.py
"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_metrics_returns_prometheus_exposition() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_metrics_actually_records_requests() -> None:
    """The previous version of this test only checked the content-type
    header, which an entirely empty Prometheus response would also
    satisfy. This asserts all three cardinality-safe labels together —
    method, route, status_code — rather than merely proving that some
    metric and some /healthz text exist somewhere in the body."""
    with TestClient(create_app()) as client:
        client.get("/healthz")
        response = client.get("/metrics")
    body = response.text
    assert (
        'http_requests_total{method="GET",route="/healthz",status_code="200"}' in body
    )


def test_metrics_collapses_unmatched_routes_to_bounded_label() -> None:
    """Proves the actual operational property that matters: hitting
    many different nonexistent paths must not create one Prometheus
    time series per path (a real cardinality-explosion risk), but
    collapse to one bounded sentinel label instead."""
    with TestClient(create_app()) as client:
        client.get("/does-not-exist-123")
        client.get("/does-not-exist-456")
        response = client.get("/metrics")

    assert 'route="__unmatched__"' in response.text
    assert "/does-not-exist-123" not in response.text
    assert "/does-not-exist-456" not in response.text
