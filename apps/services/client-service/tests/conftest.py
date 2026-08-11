"""
tests/conftest.py

Shared fixtures for real ES256/JWKS test infrastructure — at the
tests/ ROOT (promoted from tests/unit/conftest.py), so both
tests/unit/security/, tests/unit/api/, and tests/integration/ inherit
it. This is the trigger tests/unit/conftest.py's own docstring named
in advance ("promote once the real integration tier needs the same
infrastructure") — feature/client-service-clients-api's cross-tenant
matrix is the first test that actually needs real signed JWTs against
the real create_app(), not a speculative move made ahead of that need.

Plain constants/classes/helpers live in tests/unit/auth_fixtures.py;
this file only holds the actual @pytest.fixture-decorated functions.
"""

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.config import Settings
from tests.unit.auth_fixtures import TEST_AUDIENCE, TEST_ISSUER, start_jwks_server


@pytest.fixture
def keypair():
    """A fresh ES256 (P-256) keypair per test — not shared across
    tests, so tests that need a signature-mismatch scenario (signing
    with a DIFFERENT key than the one published in JWKS) can generate
    a genuinely independent second keypair without any risk of
    accidental reuse."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    return private_key, private_key.public_key()


@pytest.fixture
def jwks_server(keypair):
    """Real local HTTP server publishing the test keypair's public key
    as a real JWKS response, for the duration of one test."""
    _private_key, public_key = keypair
    server, handle = start_jwks_server(public_key)

    yield handle

    server.shutdown()
    server.server_close()


@pytest.fixture
def settings(jwks_server) -> Settings:
    return Settings(
        JWKS_URL=jwks_server.url,
        JWKS_ISSUER=TEST_ISSUER,
        JWKS_AUDIENCE=TEST_AUDIENCE,
        JWKS_ALGORITHM="ES256",
        JWKS_CACHE_TTL_SECONDS=3600,
        JWKS_FETCH_TIMEOUT_SECONDS=5,
    )
