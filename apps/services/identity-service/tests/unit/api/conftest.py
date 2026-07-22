"""tests/unit/api/conftest.py

Shared fixtures for route-level tests. Uses the SAME create_app()
factory the real application uses (see app/main.py) — not a hand-
assembled duplicate FastAPI app that risks silently diverging from it
as main.py grows.

`registry` is built first and passed INTO create_app() explicitly,
rather than letting create_app() build its own internally — this is
what guarantees a test manipulating `registry` directly (e.g. seeding
a second membership before an HTTP call) is touching the exact same
object graph the app's routes are using, not a second, disconnected
one from calling build_services() twice.

The client fixture uses TestClient as an explicit context manager
(`with ... as`), which is what actually triggers the lifespan handler
to run — without it, app.state would never get populated at all.

Local fixtures of the same name in existing test files (test_
dependencies.py, test_auth_dependency.py) already take precedence over
these for their own files, per normal pytest fixture resolution —
nothing here changes their behavior.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import ServiceRegistry, build_services
from app.core.config import Settings
from app.main import create_app
from scripts.generate_signing_keypair import generate_keypair


@pytest.fixture
def registry(tmp_path) -> ServiceRegistry:
    generate_keypair(tmp_path)
    return build_services(Settings(SECRETS_DIR=tmp_path))


@pytest.fixture
def app(registry: ServiceRegistry) -> FastAPI:
    return create_app(Settings(), registry=registry)


@pytest.fixture
def client(app: FastAPI):
    with TestClient(app) as test_client:
        yield test_client
