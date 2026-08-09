"""
tests/unit/security/conftest.py

Fixtures for TokenVerifier tests. Serves a REAL JWKS response over a
REAL local HTTP server (stdlib http.server, background thread, bound
to 127.0.0.1 on an ephemeral port) rather than mocking the HTTP layer
— matching this codebase's consistent "real objects, not mocks"
testing convention (in-memory repositories throughout client-service,
real ES256 crypto in identity-service's own TokenService tests).
PyJWKClient uses urllib internally, not httpx, so an httpx-level mock
wouldn't even intercept these calls correctly — a real socket is both
more accurate here and more consistent with how this project tests
everything else.

_build_jwk() is a small, test-only reimplementation of identity-
service's app/security/jwt.py:build_jwk() — reimplemented rather than
imported, since client-service must never import identity-service's
Python code, including for test helpers (Platform Conventions §12's
reasoning applies here too, not only to production code).
"""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey

from app.core.config import Settings

TEST_KEY_ID = "test-key-001"
TEST_ISSUER = "https://identity.flowtona.dev"
TEST_AUDIENCE = "flowtona-api"


def _build_jwk(public_key: EllipticCurvePublicKey, *, key_id: str) -> dict:
    numbers = public_key.public_numbers()
    x = numbers.x.to_bytes(32, byteorder="big")
    y = numbers.y.to_bytes(32, byteorder="big")
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": base64.urlsafe_b64encode(x).rstrip(b"=").decode("ascii"),
        "y": base64.urlsafe_b64encode(y).rstrip(b"=").decode("ascii"),
        "kid": key_id,
        "use": "sig",
        "alg": "ES256",
    }


class _JWKSHandler(BaseHTTPRequestHandler):
    """Serves whatever JSON body is currently set as the class
    attribute — set per-test by the jwks_server fixture below.
    request_count lets tests PROVE caching actually happens (Platform
    Conventions §7: no per-request callback to identity-service), not
    just assume PyJWKClient's cache_keys=True does what it claims."""

    jwks_body: bytes = b'{"keys": []}'
    request_count: int = 0

    def do_GET(self) -> None:
        type(self).request_count += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.jwks_body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # silence default per-request access logging


class JWKSServerHandle:
    """What jwks_server yields — the URL to configure JWKS_URL with,
    plus a live view of how many requests the server has actually
    received."""

    def __init__(self, url: str) -> None:
        self.url = url

    @property
    def request_count(self) -> int:
        return _JWKSHandler.request_count


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
    jwk = _build_jwk(public_key, key_id=TEST_KEY_ID)
    body = json.dumps({"keys": [jwk]}).encode("utf-8")
    _JWKSHandler.jwks_body = body
    _JWKSHandler.request_count = 0

    server = HTTPServer(("127.0.0.1", 0), _JWKSHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield JWKSServerHandle(f"http://127.0.0.1:{port}/.well-known/jwks.json")

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
