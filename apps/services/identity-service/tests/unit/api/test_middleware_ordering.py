"""tests/unit/api/test_middleware_ordering.py

Verifies that request.state.request_id is available to the registered
RFC 9457 handlers when an expected application exception is handled.

Starlette executes installed user middleware outside ExceptionMiddleware,
so request-ID middleware runs before handled exceptions from routing,
dependencies, or endpoints reach the application's exception handlers.

These tests cover handled application errors. They do not cover
unexpected exceptions processed by Starlette's outer
ServerErrorMiddleware.
"""


class TestRequestIdAvailableDuringHandledException:
    def test_generated_request_id_survives_a_handled_error(self, client):
        """Trigger a handled authentication error and confirm that the
        request ID written by middleware is available to the RFC 9457
        exception handler and propagated consistently into the
        response."""
        response = client.post("/v1/auth/logout-all-for-tenant")

        assert response.status_code == 401
        assert "X-Request-ID" in response.headers
        assert response.headers["X-Request-ID"] == response.json()["request_id"]

    def test_honors_caller_supplied_request_id_through_handled_error(self, client):
        response = client.post(
            "/v1/auth/logout-all-for-tenant",
            headers={"X-Request-ID": "caller-supplied-id"},
        )

        assert response.status_code == 401
        assert response.headers["X-Request-ID"] == "caller-supplied-id"
        assert response.json()["request_id"] == "caller-supplied-id"
