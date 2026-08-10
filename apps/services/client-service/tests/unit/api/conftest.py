"""
tests/unit/api/conftest.py

These use TestClient, real FastAPI dependency resolution, and real
ES256 crypto (a real local JWKS HTTP server), but a throwaway
hand-assembled app — NOT the real create_app(), which doesn't exist
yet (no main.py). Platform Conventions §8 specifically reserves the
term "integration test" for tests using the real (not hand-assembled)
create_app() — so these stay under tests/unit/, matching identity-
service's own test_auth_dependency.py, which uses this exact same
pattern and lives under tests/unit/api/ too. keypair/jwks_server/
settings fixtures are inherited automatically from tests/conftest.py
(the shared root, not imported from another package's conftest.py).
This file only adds what's specific to API dependency tests.
"""

import pytest

from app.security.token_verifier import TokenVerifier


@pytest.fixture
def token_verifier(settings) -> TokenVerifier:
    return TokenVerifier(settings)
