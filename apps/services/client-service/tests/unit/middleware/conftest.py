"""
tests/unit/middleware/conftest.py

One shared throwaway FastAPI app, with both RequestIDMiddleware and
MetricsMiddleware registered together — matching how they'll actually
run in production. Testing them in isolation from each other would
miss real interaction behavior (e.g. whether MetricsMiddleware's
finally block still runs correctly when RequestIDMiddleware wraps it).

/v1/broken deliberately has NO registered exception handler on this
throwaway app — unlike the real app/api/errors.py, which registers a
handler for the bare Exception class. This is intentional: it's what
lets these tests directly observe the ServerErrorMiddleware boundary
(Starlette's own generic error handling, outside either middleware's
reach) rather than the real app's own handled path.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.middleware.metrics import add_metrics_middleware
from app.middleware.request_id import add_request_id_middleware


def _build_test_app() -> FastAPI:
    app = FastAPI()
    add_request_id_middleware(app)
    add_metrics_middleware(app)

    @app.get("/v1/clients/{client_id}")
    async def _get_client(client_id: str) -> dict:
        return {"client_id": client_id}

    @app.post("/v1/clients")
    async def _create_client() -> dict:
        return {"created": True}

    @app.get("/v1/broken")
    async def _broken() -> dict:
        raise RuntimeError("deliberate failure — no handler registered for this")

    @app.get("/echo-request-id")
    async def _echo_request_id(request: Request) -> dict:
        return {"seen_by_route": request.state.request_id}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_test_app(), raise_server_exceptions=False)
