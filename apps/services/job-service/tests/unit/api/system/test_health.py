"""
tests/unit/api/system/test_health.py

Uses `with TestClient(...) as client:` — lifespan must actually run for
app.state.settings/services to be populated.
"""

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_returns_probe_contract() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"probe": "health", "status": "ok"}


def test_readyz_succeeds_unconditionally() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"probe": "readiness", "status": "ready"}


def test_startupz_succeeds_unconditionally() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/startupz")
    assert response.status_code == 200
    assert response.json() == {"probe": "startup", "status": "started"}


def test_readyz_and_startupz_have_distinct_probe_contracts() -> None:
    """Renamed from test_..._are_independent_probes — the original name
    and docstring claimed this test would catch a future refactor that
    merges readiness/startup into one shared internal decision
    function, which it cannot actually detect (a single shared function
    could easily produce these same two response bodies and this test
    would still pass). What this test genuinely verifies is the
    observable contract: the two endpoints return different `probe`
    values. The architectural rule that they must stay independently
    evolvable belongs in platform-conventions.md, not in a test
    pretending to inspect implementation structure it can't see."""
    with TestClient(create_app()) as client:
        ready = client.get("/readyz")
        startup = client.get("/startupz")
    assert ready.json()["probe"] == "readiness"
    assert startup.json()["probe"] == "startup"


def test_every_response_carries_a_request_id_header() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


def test_incoming_request_id_is_honored() -> None:
    with TestClient(create_app()) as client:
        response = client.get(
            "/healthz", headers={"X-Request-ID": "caller-supplied-id"}
        )
    assert response.headers["x-request-id"] == "caller-supplied-id"
