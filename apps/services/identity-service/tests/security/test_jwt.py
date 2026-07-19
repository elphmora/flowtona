"""tests/security/test_jwt.py

Mandatory security test category (Decision 16).
"""

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.security.jwt import build_jwk, decode_jwt, encode_jwt


def _raw_token_with_header(header: dict) -> str:
    """Constructs a JWT-shaped string directly, bypassing pyjwt.encode()
    entirely — needed to test decode_jwt()'s defenses against a
    malformed header an attacker could hand-craft directly (raw
    base64url-encoded JSON), which pyjwt.encode() itself refuses to
    produce (it validates kid is a string at encode time, so it can
    never be used to construct the malformed tokens this needs to
    test). Payload content and signature bytes are irrelevant here —
    decode_jwt()'s kid check happens before either is ever inspected."""

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_b64 = b64url(json.dumps(header).encode())
    payload_b64 = b64url(json.dumps({"sub": "irrelevant"}).encode())
    fake_signature_b64 = b64url(b"not-a-real-signature")
    return f"{header_b64}.{payload_b64}.{fake_signature_b64}"


@pytest.fixture(scope="module")
def keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="module")
def p384_keypair():
    private_key = ec.generate_private_key(ec.SECP384R1())
    return private_key, private_key.public_key()


def _base_claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(uuid.uuid4()),
        "iss": "https://identity.flowtona.dev",
        "aud": "flowtona-api",
        "iat": now,
        "exp": now + timedelta(minutes=15),
        "token_type": "access",
        "jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    return claims


class TestEncodeDecodeRoundtrip:
    def test_valid_token_roundtrips_correctly(self, keypair):
        private_key, public_key = keypair
        claims = _base_claims()

        token = encode_jwt(claims, private_key=private_key, key_id="test-key-1")
        decoded = decode_jwt(
            token,
            public_keys_by_id={"test-key-1": public_key},
            issuer="https://identity.flowtona.dev",
            audience="flowtona-api",
        )

        assert decoded["sub"] == claims["sub"]

    def test_kid_header_is_set(self, keypair):
        private_key, _ = keypair
        token = encode_jwt(_base_claims(), private_key=private_key, key_id="test-key-1")
        header = pyjwt.get_unverified_header(token)

        assert header["kid"] == "test-key-1"
        assert header["alg"] == "ES256"


class TestDecodeRejections:
    def test_wrong_audience_is_rejected(self, keypair):
        private_key, public_key = keypair
        token = encode_jwt(
            _base_claims(aud="wrong-audience"), private_key=private_key, key_id="k1"
        )

        with pytest.raises(pyjwt.InvalidAudienceError):
            decode_jwt(
                token,
                public_keys_by_id={"k1": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )

    def test_wrong_issuer_is_rejected(self, keypair):
        private_key, public_key = keypair
        token = encode_jwt(
            _base_claims(iss="https://evil.example.com"),
            private_key=private_key,
            key_id="k1",
        )

        with pytest.raises(pyjwt.InvalidIssuerError):
            decode_jwt(
                token,
                public_keys_by_id={"k1": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )

    def test_expired_token_is_rejected(self, keypair):
        private_key, public_key = keypair
        now = datetime.now(timezone.utc)
        token = encode_jwt(
            _base_claims(iat=now - timedelta(hours=1), exp=now - timedelta(minutes=1)),
            private_key=private_key,
            key_id="k1",
        )

        with pytest.raises(pyjwt.ExpiredSignatureError):
            decode_jwt(
                token,
                public_keys_by_id={"k1": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )

    def test_tampered_signature_is_rejected(self, keypair):
        private_key, public_key = keypair
        token = encode_jwt(_base_claims(), private_key=private_key, key_id="k1")
        tampered = token[:-4] + ("A" * 4)

        with pytest.raises(pyjwt.InvalidSignatureError):
            decode_jwt(
                tampered,
                public_keys_by_id={"k1": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )

    @pytest.mark.parametrize(
        "missing_claim", ["sub", "iss", "aud", "iat", "exp", "token_type", "jti"]
    )
    def test_missing_required_claim_is_rejected(self, keypair, missing_claim):
        private_key, public_key = keypair
        claims = _base_claims()
        del claims[missing_claim]
        token = encode_jwt(claims, private_key=private_key, key_id="k1")

        with pytest.raises(pyjwt.MissingRequiredClaimError):
            decode_jwt(
                token,
                public_keys_by_id={"k1": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )


class TestKidValidation:
    def test_unrecognized_kid_is_rejected(self, keypair):
        private_key, public_key = keypair
        token = encode_jwt(
            _base_claims(), private_key=private_key, key_id="unknown-kid"
        )

        with pytest.raises(pyjwt.InvalidTokenError):
            decode_jwt(
                token,
                public_keys_by_id={"the-real-kid": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )

    def test_missing_kid_is_rejected(self, keypair):
        """A token with no kid header at all — constructed directly via
        PyJWT, bypassing encode_jwt(), since encode_jwt() always sets one."""
        private_key, public_key = keypair
        token = pyjwt.encode(
            _base_claims(), private_key, algorithm="ES256"
        )  # no kid header

        with pytest.raises(pyjwt.InvalidTokenError):
            decode_jwt(
                token,
                public_keys_by_id={"some-kid": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )

    def test_non_string_kid_is_rejected(self, keypair):
        """A malformed kid (e.g. a list) must fail cleanly through the
        same InvalidTokenError path as any other bad token. Uses
        _raw_token_with_header() rather than pyjwt.encode() — PyJWT's
        own encode() already validates kid is a string at construction
        time, so it can never be used to produce the malformed token
        this test needs; a hand-crafted JWT bypasses that entirely, the
        same way a real attacker would."""
        _, public_key = keypair
        token = _raw_token_with_header({"alg": "ES256", "kid": ["not", "a", "string"]})

        with pytest.raises(pyjwt.InvalidTokenError):
            decode_jwt(
                token,
                public_keys_by_id={"some-kid": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )

    def test_empty_string_kid_is_rejected(self, keypair):
        private_key, public_key = keypair
        token = pyjwt.encode(
            _base_claims(), private_key, algorithm="ES256", headers={"kid": ""}
        )

        with pytest.raises(pyjwt.InvalidTokenError):
            decode_jwt(
                token,
                public_keys_by_id={"some-kid": public_key},
                issuer="https://identity.flowtona.dev",
                audience="flowtona-api",
            )


class TestBuildJwk:
    def test_produces_expected_fields(self, keypair):
        _, public_key = keypair
        jwk = build_jwk(public_key, key_id="test-key-1")

        assert jwk["kty"] == "EC"
        assert jwk["crv"] == "P-256"
        assert jwk["kid"] == "test-key-1"
        assert jwk["use"] == "sig"
        assert jwk["alg"] == "ES256"

    def test_x_and_y_are_valid_base64url(self, keypair):
        _, public_key = keypair
        jwk = build_jwk(public_key, key_id="test-key-1")

        for coord in (jwk["x"], jwk["y"]):
            padded = coord + "=" * (-len(coord) % 4)
            decoded = base64.urlsafe_b64decode(padded)
            assert len(decoded) == 32  # P-256 coordinates are 32 bytes

    def test_rejects_non_p256_curve(self, p384_keypair):
        """A P-384 key is a valid EllipticCurvePublicKey but must be
        rejected here — the returned JWK always advertises
        "crv": "P-256" / "alg": "ES256" regardless of the key's actual
        curve, so a P-384 key would otherwise produce a JWK that lies
        about its own algorithm."""
        _, p384_public_key = p384_keypair

        with pytest.raises(ValueError):
            build_jwk(p384_public_key, key_id="test-key-1")

    def test_rejects_non_ec_key(self):
        """Defensive check at this boundary, not just relying on the
        type hint — jwt.py is meant to work as a standalone primitive,
        independent of whatever caller-side validation TokenService
        happens to do before calling this. Without this check, a
        non-EC key would fail with an AttributeError from the curve
        access instead of a clean ValueError."""
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_public_key = rsa_key.public_key()

        with pytest.raises(ValueError):
            build_jwk(rsa_public_key, key_id="test-key-1")
