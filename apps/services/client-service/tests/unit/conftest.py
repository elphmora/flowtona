"""
tests/unit/conftest.py

Shared fixtures for real ES256/JWKS test infrastructure — automatically
available to every test package under tests/unit/ (security/, api/,
and any future package needing the same infrastructure) via pytest's
standard conftest.py inheritance. Promoted here from tests/unit/
security/conftest.py once a second package (tests/unit/api/) needed
the same infrastructure — a concrete reuse need, not premature
abstraction.

When Platform Conventions §8's real "integration test" tier
(tests/integration/, real create_app()) eventually needs the same
infrastructure, promote this one file up to tests/conftest.py then —
a cheap, well-understood move, not a reason to place it there
speculatively now for a need that doesn't exist yet.

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
