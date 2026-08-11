"""
tests/unit/api/system/conftest.py

Throwaway app registering all three system routers together, plus the
observability middleware — needed so test_system_metrics.py can prove
/metrics actually exposes real data the middleware recorded, not just
that the endpoint returns 200. Not the real create_app() (doesn't
exist yet), so these stay under tests/unit/ per Platform Conventions
§8 Amendment 5 — same reasoning as every other API test in this
codebase so far.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.system.health import router as system_health_router
from app.api.system.info import router as system_info_router
from app.api.system.metrics import router as system_metrics_router
from app.middleware.metrics import add_metrics_middleware
from app.middleware.request_id import add_request_id_middleware


def _build_test_app() -> FastAPI:
    app = FastAPI()
    add_request_id_middleware(app)
    add_metrics_middleware(app)
    app.include_router(system_health_router)
    app.include_router(system_info_router)
    app.include_router(system_metrics_router)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_test_app())
