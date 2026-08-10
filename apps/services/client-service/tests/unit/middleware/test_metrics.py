"""
tests/unit/middleware/test_metrics.py

Converts scripts/smoke_test_middleware.py's manually-confirmed metrics
behaviors into a permanent regression suite.

Reads metric values via .collect(), never via .labels(...) directly —
calling .labels(...) itself creates a new zero-valued entry for that
label combination as a side effect, which would pollute the exact
label sets these tests need to inspect. Asserts on DELTAS (before vs
after each test action), never absolute totals: REQUEST_COUNT and
REQUEST_LATENCY_SECONDS are module-level Prometheus singletons that
persist and accumulate across every test in the same process, not
reset per test — an absolute-count assertion would be fragile and
order-dependent across the whole suite, not just within this file.
"""

from app.middleware.metrics import (
    _UNMATCHED_ROUTE,
    REQUEST_COUNT,
    REQUEST_LATENCY_SECONDS,
)


def _counter_value(counter, **labels) -> float:
    for sample in counter.collect()[0].samples:
        if sample.name.endswith("_total") and sample.labels == labels:
            return sample.value
    return 0.0


def _histogram_observation_count(histogram, **labels) -> float:
    for sample in histogram.collect()[0].samples:
        if sample.name.endswith("_count") and sample.labels == labels:
            return sample.value
    return 0.0


class TestRouteTemplateLabeling:
    """The core cardinality-safety proof: requests to different
    resolved paths under the same route must record under the SAME
    route label, never under the raw resolved path with real values
    substituted in (Platform Conventions §10)."""

    def test_different_resolved_ids_collapse_onto_one_route_label(self, client):
        route = "/v1/clients/{client_id}"
        before = _counter_value(
            REQUEST_COUNT, method="GET", route=route, status_code="200"
        )

        client.get("/v1/clients/aaa")
        client.get("/v1/clients/bbb")
        client.get("/v1/clients/ccc")

        after = _counter_value(
            REQUEST_COUNT, method="GET", route=route, status_code="200"
        )
        assert after - before == 3

    def test_raw_resolved_path_never_appears_as_its_own_label(self, client):
        marker = "some-genuinely-unique-marker-xyz"
        client.get(f"/v1/clients/{marker}")

        for sample in REQUEST_COUNT.collect()[0].samples:
            assert sample.labels.get("route") != f"/v1/clients/{marker}"


class TestUnmatchedRouteCardinality:
    def test_different_unmatched_paths_collapse_onto_one_sentinel(self, client):
        before = _counter_value(
            REQUEST_COUNT, method="GET", route=_UNMATCHED_ROUTE, status_code="404"
        )

        client.get("/nope/1")
        client.get("/nope/2")
        client.get("/genuinely/nonexistent/path/xyz")

        after = _counter_value(
            REQUEST_COUNT, method="GET", route=_UNMATCHED_ROUTE, status_code="404"
        )
        assert after - before == 3

    def test_unmatched_path_never_appears_as_its_own_label(self, client):
        marker = "another-unique-nonexistent-marker-abc"
        client.get(f"/{marker}")

        for sample in REQUEST_COUNT.collect()[0].samples:
            assert sample.labels.get("route") != f"/{marker}"


class TestAbortedRequestSemantics:
    """The status_code semantic-cleanliness fix: http_requests_total
    only counts a response that was ACTUALLY emitted — an aborted
    request (uncaught exception, no response ever started through this
    middleware) must not pollute that counter with a synthetic status.
    Its latency IS still meaningful and IS still recorded, under the
    same method/route labels."""

    def test_aborted_request_does_not_increment_request_count(self, client):
        route = "/v1/broken"
        before = sum(
            sample.value
            for sample in REQUEST_COUNT.collect()[0].samples
            if sample.name.endswith("_total") and sample.labels.get("route") == route
        )

        client.get("/v1/broken")

        after = sum(
            sample.value
            for sample in REQUEST_COUNT.collect()[0].samples
            if sample.name.endswith("_total") and sample.labels.get("route") == route
        )
        assert after == before

    def test_aborted_request_still_records_latency(self, client):
        route = "/v1/broken"
        before = _histogram_observation_count(
            REQUEST_LATENCY_SECONDS, method="GET", route=route
        )

        client.get("/v1/broken")

        after = _histogram_observation_count(
            REQUEST_LATENCY_SECONDS, method="GET", route=route
        )
        assert after - before == 1


class TestNormalRequestMetrics:
    def test_successful_request_increments_count_and_latency(self, client):
        route = "/v1/clients/{client_id}"
        count_before = _counter_value(
            REQUEST_COUNT, method="GET", route=route, status_code="200"
        )
        latency_before = _histogram_observation_count(
            REQUEST_LATENCY_SECONDS, method="GET", route=route
        )

        client.get("/v1/clients/some-id")

        count_after = _counter_value(
            REQUEST_COUNT, method="GET", route=route, status_code="200"
        )
        latency_after = _histogram_observation_count(
            REQUEST_LATENCY_SECONDS, method="GET", route=route
        )
        assert count_after - count_before == 1
        assert latency_after - latency_before == 1

    def test_post_request_recorded_with_correct_method_label(self, client):
        """Every other test in this suite uses GET — this is the only
        proof that the method label genuinely reflects the real HTTP
        method, not hardcoded or defaulted."""
        route = "/v1/clients"
        before = _counter_value(
            REQUEST_COUNT, method="POST", route=route, status_code="200"
        )

        client.post("/v1/clients")

        after = _counter_value(
            REQUEST_COUNT, method="POST", route=route, status_code="200"
        )
        assert after - before == 1

    def test_post_request_gets_request_id(self, client):
        response = client.post("/v1/clients")
        assert "x-request-id" in response.headers


class TestHistogramLabelSet:
    def test_latency_histogram_has_no_status_code_label(self, client):
        """Guards an intentional design decision: REQUEST_LATENCY_SECONDS
        is labeled by method/route only, deliberately NOT status_code.
        A histogram already carries a higher cardinality cost per label
        than a counter (each bucket boundary multiplies out), so adding
        status_code here would multiply that cost for little
        diagnostic value REQUEST_COUNT doesn't already provide. Guards
        against someone adding it later without noticing the
        cardinality implication."""
        client.get("/v1/clients/label-check-marker")

        matching = [
            sample
            for sample in REQUEST_LATENCY_SECONDS.collect()[0].samples
            if sample.name.endswith("_count")
            and sample.labels.get("route") == "/v1/clients/{client_id}"
        ]
        assert len(matching) >= 1
        assert set(matching[0].labels.keys()) == {"method", "route"}
