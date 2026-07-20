"""tests/unit/api/test_errors.py

Builds a minimal throwaway FastAPI app with dummy routes that
intentionally raise each exception type — no real routes exist yet to
exercise this through, and the exception-handling behavior itself is
what's under test here, not any particular endpoint.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import register_exception_handlers
from app.exceptions.base import DomainError, IdentityInvariantError
from app.middleware.request_id import add_request_id_middleware


class _SampleDomainError(DomainError):
    code = "sample_domain_error"
    status_code = 409
    title = "Sample Domain Error"

    def __init__(self) -> None:
        super().__init__("This is a sample domain error for testing.")


class _RequestBody(BaseModel):
    required_field: str


class _Address(BaseModel):
    street: str


class _BodyWithNestedModel(BaseModel):
    address: _Address


def _build_test_app() -> FastAPI:
    app = FastAPI()
    add_request_id_middleware(app)
    register_exception_handlers(app)

    @app.get("/domain-error")
    async def _raise_domain_error():
        raise _SampleDomainError()

    @app.get("/invariant-error")
    async def _raise_invariant_error():
        raise IdentityInvariantError("some internal detail that must not leak")

    @app.get("/unexpected-error")
    async def _raise_unexpected_error():
        raise RuntimeError("something genuinely unplanned")

    @app.post("/validated")
    async def _validated_route(body: _RequestBody):
        return {"ok": True}

    @app.post("/validated-nested")
    async def _validated_nested_route(body: _BodyWithNestedModel):
        return {"ok": True}

    @app.get("/ok")
    async def _ok_route():
        return {"ok": True}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_test_app(), raise_server_exceptions=False)


class TestDomainErrorHandler:
    def test_returns_problem_json_shape(self, client):
        response = client.get("/domain-error")

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        assert body["code"] == "sample_domain_error"
        assert body["status"] == 409
        assert body["title"] == "Sample Domain Error"
        assert body["detail"] == "This is a sample domain error for testing."
        assert body["instance"] == "/domain-error"
        assert body["type"].endswith("/sample-domain-error")

    def test_includes_request_id(self, client):
        response = client.get("/domain-error")
        body = response.json()
        assert body["request_id"]
        assert response.headers["X-Request-ID"] == body["request_id"]

    def test_honors_incoming_request_id(self, client):
        response = client.get(
            "/domain-error", headers={"X-Request-ID": "caller-supplied-id"}
        )
        assert response.headers["X-Request-ID"] == "caller-supplied-id"
        assert response.json()["request_id"] == "caller-supplied-id"


class TestIdentityInvariantErrorHandler:
    def test_returns_generic_500_without_leaking_detail(self, client):
        response = client.get("/invariant-error")

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "internal_server_error"
        assert body["detail"] == "An internal server error occurred."
        # The actual internal diagnostic message must never reach the client.
        assert "internal detail" not in response.text


class TestValidationErrorHandler:
    def test_malformed_body_returns_problem_json_shape(self, client):
        response = client.post("/validated", json={})  # missing required_field

        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"
        body = response.json()
        assert body["code"] == "validation_failed"
        assert body["status"] == 422

    def test_includes_field_level_error_detail(self, client):
        """Real usability requirement, not just RFC 9457 completeness —
        without this, a client knows validation failed but not why,
        which is a regression versus FastAPI's own default behavior."""
        response = client.post("/validated", json={})

        body = response.json()
        assert "errors" in body
        assert len(body["errors"]) >= 1
        assert body["errors"][0]["field"] == "required_field"
        assert body["errors"][0]["message"]

    def test_valid_body_succeeds_normally(self, client):
        response = client.post("/validated", json={"required_field": "x"})
        assert response.status_code == 200

    def test_nested_model_field_path_is_dotted(self, client):
        """Proves the formatter itself, not just Pydantic's raw shape —
        a missing nested field must produce a readable dotted path
        (address.street), not a raw tuple or a truncated/wrong value."""
        response = client.post("/validated-nested", json={"address": {}})

        body = response.json()
        assert body["errors"][0]["field"] == "address.street"


class TestErrorsFieldOmittedWhenNotApplicable:
    def test_domain_error_response_has_no_errors_field(self, client):
        """The `errors` extension member is validation-specific — every
        other response type must omit it entirely (exclude_none), not
        include it as null."""
        response = client.get("/domain-error")
        assert "errors" not in response.json()

    def test_unexpected_error_response_has_no_errors_field(self, client):
        response = client.get("/unexpected-error")
        assert "errors" not in response.json()


class TestUnexpectedErrorHandler:
    def test_returns_generic_500_without_leaking_traceback(self, client):
        response = client.get("/unexpected-error")

        assert response.status_code == 500
        body = response.json()
        assert body["code"] == "internal_server_error"
        assert body["detail"] == "An internal server error occurred."
        assert "genuinely unplanned" not in response.text
        assert "RuntimeError" not in response.text


class TestSuccessfulRequests:
    def test_success_response_still_gets_request_id_header(self, client):
        response = client.get("/ok")
        assert response.status_code == 200
        assert response.headers["X-Request-ID"]
