"""
tests/unit/auth_fixtures.py

Plain, importable module — NOT a conftest.py — holding real ES256/JWKS
test infrastructure shared by both tests/unit/security/ and
tests/integration/api/. Deliberately not a conftest.py: conftest.py is
pytest's fixture-discovery mechanism, not a general import target, and
one test package importing another package's conftest.py makes
fixture ownership ambiguous. Actual @pytest.fixture exposure lives in
tests/unit/conftest.py, which imports from here — this file is just
constants, plain classes, and plain functions.

_build_jwk() is a small, test-only reimplementation of identity-
service's app/security/jwt.py:build_jwk() — reimplemented rather than
imported, since client-service must never import identity-service's
Python code, including for test helpers (Platform Conventions §12's
reasoning applies here too, not only to production code).
"""

import base64
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey

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
    attribute — set per-test by the jwks_server fixture (tests/unit/
    conftest.py). request_count lets tests PROVE caching actually
    happens (Platform Conventions §7: no per-request callback to
    identity-service), not just assume PyJWKClient's cache_keys=True
    does what it claims."""

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
    """What the jwks_server fixture yields — the URL to configure
    JWKS_URL with, plus a live view of how many requests the server
    has actually received."""

    def __init__(self, url: str) -> None:
        self.url = url

    @property
    def request_count(self) -> int:
        return _JWKSHandler.request_count


def start_jwks_server(
    public_key: EllipticCurvePublicKey,
) -> tuple[HTTPServer, JWKSServerHandle]:
    """Starts a real local HTTP server publishing public_key as a real
    JWKS response. Caller (the jwks_server fixture) owns shutting it
    down."""
    jwk = _build_jwk(public_key, key_id=TEST_KEY_ID)
    body = json.dumps({"keys": [jwk]}).encode("utf-8")
    _JWKSHandler.jwks_body = body
    _JWKSHandler.request_count = 0

    server = HTTPServer(("127.0.0.1", 0), _JWKSHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return server, JWKSServerHandle(f"http://127.0.0.1:{port}/.well-known/jwks.json")


def default_claims(**overrides: object) -> dict:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(uuid4()),
        "tenant_id": str(uuid4()),
        "role": "owner",
        "permissions": ["clients:read", "clients:write"],
        "permissions_version": 0,
        "token_type": "access",
        "jti": str(uuid4()),
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    claims.update(overrides)
    return claims


def make_token(
    private_key, *, key_id: str = TEST_KEY_ID, **claim_overrides: object
) -> str:
    return jwt.encode(
        default_claims(**claim_overrides),
        private_key,
        algorithm="ES256",
        headers={"kid": key_id},
    )
