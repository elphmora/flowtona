"""
tests/unit/security/test_token_verifier.py

Generates a real EC (P-256/ES256) test keypair and signs real JWTs
against it. TokenVerifier is security-critical code ported from
client-service; "it compiles and client-service has it too" is not
evidence it behaves correctly here -- this file is that evidence.

get_signing_key_from_jwt is monkeypatched at the PyJWKClient class
level, not TokenVerifier's own methods -- this is the one method
app/security/token_verifier.py actually calls directly (confirmed by
reading its source, not inferred), so its name and contract are known
with certainty. Only the JWKS network fetch is stubbed; every other
step -- signature verification, issuer/audience/expiry checks, PyJWT's
`require` option, and this codebase's own application-claim type
validation -- runs for real against real signed tokens.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.core.config import Settings
from app.exceptions.auth import InvalidAccessTokenError
from app.security.token_verifier import TokenVerifier

_KID = "test-key-1"
_ISSUER = "https://identity.flowtona.dev"
_AUDIENCE = "flowtona-api"


class _FakeSigningKey:
    def __init__(self, key: Any) -> None:
        self.key = key


@pytest.fixture(scope="module")
def keypair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        JWKS_URL="http://test-identity-service/.well-known/jwks.json",
        JWKS_ISSUER=_ISSUER,
        JWKS_AUDIENCE=_AUDIENCE,
        JWKS_ALGORITHM="ES256",
    )


@pytest.fixture
def verifier(
    settings: Settings,
    keypair: ec.EllipticCurvePrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> TokenVerifier:
    public_key = keypair.public_key()

    def _fake_get_signing_key_from_jwt(
        self: PyJWKClient, token: str
    ) -> _FakeSigningKey:
        header = jwt.get_unverified_header(token)
        if header.get("kid") != _KID:
            raise PyJWKClientError(
                f"Unable to find a signing key matching {header.get('kid')!r}"
            )
        return _FakeSigningKey(public_key)

    monkeypatch.setattr(
        PyJWKClient, "get_signing_key_from_jwt", _fake_get_signing_key_from_jwt
    )
    return TokenVerifier(settings)


def _base_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "role": "dispatcher",
        "permissions": ["jobs:write", "clients:read"],
        "permissions_version": 1,
        "token_type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return claims


def _sign(
    private_key: ec.EllipticCurvePrivateKey,
    claims: dict[str, Any],
    *,
    kid: str = _KID,
) -> str:
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": kid})


def test_verify_accepts_a_valid_token(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    token = _sign(keypair, _base_claims())
    claims = verifier.verify(token)
    assert claims.role == "dispatcher"
    assert "jobs:write" in claims.permissions
    assert claims.token_type == "access"


def test_verify_rejects_expired_token(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    token = _sign(keypair, _base_claims(exp=int(time.time()) - 10))
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_wrong_issuer(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    token = _sign(keypair, _base_claims(iss="https://not-identity.flowtona.dev"))
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_wrong_audience(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    token = _sign(keypair, _base_claims(aud="some-other-audience"))
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_wrong_token_type(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    token = _sign(keypair, _base_claims(token_type="refresh"))
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_missing_required_claim(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    claims = _base_claims()
    del claims["tenant_id"]
    token = _sign(keypair, claims)
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_malformed_permissions_claim(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    # A bare string, not a list -- exactly the wire-shape mistake the
    # isinstance() check in _build_claims exists to catch (frozenset()
    # on a bare str would otherwise silently decompose it into
    # characters rather than raising).
    token = _sign(keypair, _base_claims(permissions="jobs:write"))
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_malformed_uuid_application_claim(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    token = _sign(keypair, _base_claims(sub="not-a-uuid"))
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_unresolvable_signing_key(
    verifier: TokenVerifier, keypair: ec.EllipticCurvePrivateKey
) -> None:
    # Signed with a kid that doesn't exist in the (fake) JWKS --
    # proves the PyJWKClientError branch, not just InvalidTokenError.
    token = _sign(keypair, _base_claims(), kid="unknown-kid")
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_structurally_malformed_token(verifier: TokenVerifier) -> None:
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify("not-a-valid-jwt-at-all")


def test_verify_rejects_invalid_signature(
    verifier: TokenVerifier,
) -> None:
    """Distinct from the unresolvable-kid test above: here the kid IS
    recognised and the fake resolver returns the correct public key,
    but the token was signed with a DIFFERENT private key. Proves
    signature verification itself is real, not just key resolution."""
    different_private_key = ec.generate_private_key(ec.SECP256R1())
    token = _sign(different_private_key, _base_claims())

    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)


def test_verify_rejects_disallowed_algorithm(
    verifier: TokenVerifier,
) -> None:
    """Proves the algorithms=[JWKS_ALGORITHM] restriction in
    TokenVerifier.verify() is real -- a token signed with a different
    algorithm, even with a recognised kid, must be rejected regardless
    of what key would otherwise be resolved. The fake resolver doesn't
    inspect "alg" at all (only "kid"), so this specifically exercises
    jwt.decode()'s own algorithm restriction, not the fake."""
    token = jwt.encode(
        _base_claims(),
        "irrelevant-hmac-secret",
        algorithm="HS256",
        headers={"kid": _KID},
    )
    with pytest.raises(InvalidAccessTokenError):
        verifier.verify(token)
