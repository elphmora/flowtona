"""
tests/unit/api/system/test_health.py

Note on recommendation 6 (rename test_currently_identical_to_healthz
to test_matches_healthz_in_phase1): superseded rather than applied
directly — readyz/startupz are no longer identical to healthz at all
once the probe-specific shape fix landed (different "probe" value,
different "status" value). The tests below check what's actually true
now: readyz/startupz share healthz's SUCCESS status code and overall
correctness, not its exact body.
"""


class TestHealthz:
    def test_returns_200(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200

    def test_response_shape(self, client):
        response = client.get("/healthz")
        assert response.json() == {"probe": "health", "status": "ok"}


class TestReadyz:
    def test_returns_200_in_phase1(self, client):
        """Named for what's currently true (Phase 1: no external
        dependency to fail on), not implying this will always be 200
        — see app/api/system/health.py's module docstring for what
        changes once a real dependency (e.g. PostgreSQL) arrives."""
        response = client.get("/readyz")
        assert response.status_code == 200

    def test_response_shape(self, client):
        response = client.get("/readyz")
        assert response.json() == {"probe": "readiness", "status": "ready"}


class TestStartupz:
    def test_returns_200_in_phase1(self, client):
        response = client.get("/startupz")
        assert response.status_code == 200

    def test_response_shape(self, client):
        response = client.get("/startupz")
        assert response.json() == {"probe": "startup", "status": "started"}


class TestProbeFieldDistinguishesEndpoints:
    def test_each_probe_has_a_distinct_probe_value(self, client):
        """The whole point of the "probe" field: given only a response
        body with no other context, it must be possible to tell which
        endpoint produced it. Proves all three are actually distinct,
        not accidentally identical."""
        healthz_probe = client.get("/healthz").json()["probe"]
        readyz_probe = client.get("/readyz").json()["probe"]
        startupz_probe = client.get("/startupz").json()["probe"]

        assert len({healthz_probe, readyz_probe, startupz_probe}) == 3
