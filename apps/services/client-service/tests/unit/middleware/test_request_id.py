"""
tests/unit/middleware/test_request_id.py

Converts scripts/smoke_test_middleware.py's manually-confirmed
behaviors into a permanent regression suite. Every assertion here was
verified running once already — see client-service-architecture.md's
Entity & Convention Clarifications — this suite exists to keep that
confirmation true going forward, not to discover it for the first
time.
"""


class TestRequestIDGeneration:
    def test_generated_when_absent(self, client):
        response = client.get("/v1/clients/aaa")
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    def test_two_requests_get_different_generated_ids(self, client):
        r1 = client.get("/v1/clients/aaa")
        r2 = client.get("/v1/clients/bbb")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


class TestRequestIDPropagation:
    def test_valid_inbound_id_is_propagated_unchanged(self, client):
        response = client.get(
            "/v1/clients/aaa", headers={"X-Request-ID": "flowtona-test-123"}
        )
        assert response.headers["x-request-id"] == "flowtona-test-123"

    def test_exactly_one_response_header_no_duplication(self, client):
        """Guards the headers.append() -> assignment fix specifically
        — an earlier draft risked accumulating duplicate X-Request-ID
        response headers rather than replacing."""
        response = client.get(
            "/v1/clients/aaa", headers={"X-Request-ID": "flowtona-test-123"}
        )
        matching = [
            (name, value)
            for name, value in response.headers.raw
            if name.lower() == b"x-request-id"
        ]
        assert len(matching) == 1


class TestRequestIDValidation:
    def test_oversized_inbound_id_is_replaced(self, client):
        oversized = "a" * 500
        response = client.get("/v1/clients/aaa", headers={"X-Request-ID": oversized})
        returned = response.headers.get("x-request-id")
        assert returned is not None
        assert returned != oversized
        assert len(returned) <= 128

    def test_id_with_disallowed_characters_is_replaced(self, client):
        response = client.get(
            "/v1/clients/aaa",
            headers={"X-Request-ID": "not valid! spaces & symbols"},
        )
        assert response.headers.get("x-request-id") != "not valid! spaces & symbols"

    def test_empty_inbound_id_is_replaced(self, client):
        response = client.get("/v1/clients/aaa", headers={"X-Request-ID": ""})
        assert response.headers.get("x-request-id")

    def test_maximum_length_id_is_still_accepted(self, client):
        """Boundary case: exactly at the 128-char limit, not
        comfortably under or over it — proves the boundary check is
        the right comparison operator, not just roughly correct."""
        exactly_max = "a" * 128
        response = client.get("/v1/clients/aaa", headers={"X-Request-ID": exactly_max})
        assert response.headers.get("x-request-id") == exactly_max

    def test_over_maximum_length_id_is_replaced(self, client):
        one_over_max = "a" * 129
        response = client.get("/v1/clients/aaa", headers={"X-Request-ID": one_over_max})
        assert response.headers.get("x-request-id") != one_over_max

    def test_duplicate_inbound_header_first_value_wins(self, client):
        """Explicit, tested policy — see _extract_request_id()'s
        docstring. Uses a list of tuples, not a dict, since a Python
        dict cannot represent duplicate header names; raw ASGI headers
        (and httpx's request construction) genuinely can."""
        response = client.get(
            "/v1/clients/aaa",
            headers=[
                ("X-Request-ID", "first-value"),
                ("X-Request-ID", "second-value"),
            ],
        )
        assert response.headers.get("x-request-id") == "first-value"


class TestRequestIDStateAvailability:
    def test_request_id_seen_by_route_matches_response_header(self, client):
        """Proves scope["state"]["request_id"] is genuinely readable
        downstream (via request.state.request_id), not just present on
        the response header — these are two different code paths
        (send_wrapper's header injection vs scope state assignment), a
        bug could make one work without the other."""
        response = client.get("/echo-request-id")
        assert response.json()["seen_by_route"] == response.headers["x-request-id"]


class TestUncaughtExceptionBoundary:
    """The confirmed, correct limitation this design turned on — see
    client-service-architecture.md for the full Starlette-internals
    reasoning this is derived from, and the smoke test run that
    empirically confirmed it."""

    def test_uncaught_exception_returns_500(self, client):
        response = client.get("/v1/broken")
        assert response.status_code == 500

    def test_uncaught_exception_response_has_no_request_id_header(self, client):
        """Not a bug: a response built entirely by Starlette's own
        generic error handling (ServerErrorMiddleware, outside this
        middleware's reach) never passes through
        RequestIDMiddleware's send_wrapper at all."""
        response = client.get("/v1/broken")
        assert "x-request-id" not in response.headers


class TestHandledExceptionPath:
    """Contrasts directly with TestUncaughtExceptionBoundary: an
    exception with a REGISTERED handler (the same category
    app/api/errors.py's DomainError/RequestValidationError handlers
    belong to, distinct from the bare-Exception handler that lives on
    ServerErrorMiddleware instead) produces a normal Response that DOES
    pass back through both user middlewares. Uses its own app, not the
    shared fixture, since it needs a registered handler the shared
    fixture deliberately doesn't have."""

    def test_handled_exception_response_has_request_id_header(self):
        from fastapi import FastAPI
        from fastapi.requests import Request
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient

        from app.middleware.metrics import add_metrics_middleware
        from app.middleware.request_id import add_request_id_middleware

        class _NotFoundError(Exception):
            pass

        async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=404, content={"detail": "not found"})

        app = FastAPI()
        add_request_id_middleware(app)
        add_metrics_middleware(app)
        app.add_exception_handler(_NotFoundError, _handle_not_found)

        @app.get("/v1/handled-error")
        async def _raise_handled() -> dict:
            raise _NotFoundError()

        local_client = TestClient(app, raise_server_exceptions=False)
        response = local_client.get("/v1/handled-error")

        assert response.status_code == 404
        assert "x-request-id" in response.headers
