"""
tests/unit/security/test_token_verifier.py

TokenVerifier tests against Platform Conventions §7's full consumer
verification checklist — real ES256 signing, real JWKS served over a
real local HTTP server (see conftest.py), no mocked crypto or network
layer.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.exceptions.auth import InvalidAccessTokenError
from app.security.token_verifier import TokenVerifier
from tests.unit.security.conftest import TEST_AUDIENCE, TEST_ISSUER, TEST_KEY_ID


def _default_claims(**overrides) -> dict:
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


def _make_token(private_key, *, key_id: str = TEST_KEY_ID, **claim_overrides) -> str:
    return jwt.encode(
        _default_claims(**claim_overrides),
        private_key,
        algorithm="ES256",
        headers={"kid": key_id},
    )


def _make_alg_none_token(private_key, *, key_id: str = TEST_KEY_ID) -> str:
    """Manually crafts an unsigned "alg: none" token by signing
    normally, then rewriting the header to claim alg=none and
    discarding the signature — the classic alg-confusion attack.
    Platform Conventions §7 explicitly requires rejecting alg: none;
    this proves it's actually rejected, not just documented as a
    requirement."""
    valid_token = _make_token(private_key, key_id=key_id)
    header_b64, payload_b64, _signature_b64 = valid_token.split(".")

    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    header["alg"] = "none"
    tampered_header_b64 = (
        base64.urlsafe_b64encode(json.dumps(header).encode("utf-8"))
        .rstrip(b"=")
        .decode("ascii")
    )

    return f"{tampered_header_b64}.{payload_b64}."


class TestValidToken:
    def test_returns_correct_claims(self, keypair, settings):
        private_key, _public_key = keypair
        sub, tenant_id = uuid4(), uuid4()
        token = _make_token(
            private_key,
            sub=str(sub),
            tenant_id=str(tenant_id),
            permissions=["clients:read"],
        )

        claims = TokenVerifier(settings).verify(token)

        assert claims.sub == sub
        assert claims.tenant_id == tenant_id
        assert claims.role == "owner"
        assert claims.permissions == frozenset({"clients:read"})
        assert claims.permissions_version == 0
        assert claims.token_type == "access"
        assert claims.jti is not None


class TestSignatureAndKeyResolution:
    def test_wrong_signature_raises(self, settings):
        """Signed with a DIFFERENT keypair than the one published in
        JWKS — same kid claimed in the header, but the signature
        cannot verify against the actually-published public key."""
        wrong_key = ec.generate_private_key(ec.SECP256R1())
        token = _make_token(wrong_key)

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    def test_unknown_kid_raises(self, keypair, settings):
        private_key, _public_key = keypair
        token = _make_token(private_key, key_id="a-kid-that-does-not-exist")

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    def test_alg_none_attack_raises(self, keypair, settings):
        private_key, _public_key = keypair
        token = _make_alg_none_token(private_key)

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    @pytest.mark.parametrize("garbage", ["not-a-jwt", "a.b", "", "a.b.c.d"])
    def test_structurally_malformed_token_raises_without_leaking_pyjwt_exception(
        self, settings, garbage
    ):
        """get_signing_key_from_jwt() parses the token's own header to
        read kid, BEFORE jwt.decode() ever runs — confirmed empirically
        that a structurally malformed token raises DecodeError at this
        stage, not PyJWKClientError. Proves this doesn't leak a raw
        PyJWT exception type past verify(), only InvalidAccessTokenError
        — the exact gap caught while writing this test."""
        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(garbage)


class TestStandardClaims:
    def test_wrong_issuer_raises(self, keypair, settings):
        private_key, _public_key = keypair
        token = _make_token(private_key, iss="https://not-identity-service.example")

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    def test_wrong_audience_raises(self, keypair, settings):
        private_key, _public_key = keypair
        token = _make_token(private_key, aud="some-other-service")

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    def test_expired_token_raises(self, keypair, settings):
        private_key, _public_key = keypair
        now = datetime.now(timezone.utc)
        token = _make_token(
            private_key, iat=now - timedelta(hours=1), exp=now - timedelta(minutes=1)
        )

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)


class TestTokenType:
    def test_token_type_not_access_raises(self, keypair, settings):
        """A token carrying every required claim EXCEPT the right
        token_type — isolates the token_type gate specifically, from
        the missing-claims case tested separately below."""
        private_key, _public_key = keypair
        token = _make_token(private_key, token_type="preauth")

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    def test_realistic_preauth_shaped_token_raises(self, keypair, settings):
        """A REAL preauth token from identity-service doesn't carry
        tenant_id/role/permissions/permissions_version at all (its
        actual claims shape, per identity-service's TokenService) — a
        genuine preauth token is rejected earlier, at the required-
        claims stage, not at the token_type check. Both paths reject
        it; this proves the more realistic one does too, not just the
        artificially-isolated case above."""
        private_key, _public_key = keypair
        now = datetime.now(timezone.utc)
        minimal_preauth_claims = {
            "sub": str(uuid4()),
            "token_type": "preauth",
            "jti": str(uuid4()),
            "iss": TEST_ISSUER,
            "aud": TEST_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=120),
        }
        token = jwt.encode(
            minimal_preauth_claims,
            private_key,
            algorithm="ES256",
            headers={"kid": TEST_KEY_ID},
        )

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)


class TestRequiredClaims:
    @pytest.mark.parametrize(
        "missing_claim",
        [
            "sub",
            "tenant_id",
            "role",
            "permissions",
            "permissions_version",
            "token_type",
            "jti",
        ],
    )
    def test_missing_required_claim_raises(self, keypair, settings, missing_claim):
        private_key, _public_key = keypair
        claims = _default_claims()
        del claims[missing_claim]
        token = jwt.encode(
            claims, private_key, algorithm="ES256", headers={"kid": TEST_KEY_ID}
        )

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)


class TestMalformedApplicationClaims:
    """Proves a real gap caught while writing these tests: frozenset()
    on a bare str silently decomposes it into individual characters
    rather than raising — permissions must be validated as a list of
    strings before conversion, not passed through frozenset()
    unchecked (see the fix in token_verifier.py)."""

    @pytest.mark.parametrize(
        "malformed_permissions",
        [
            "clients:read",  # bare str — would silently decompose into chars
            {"clients:read": 1},  # dict
            ["clients:read", 7],  # list with a non-str item
            123,  # not a collection at all
            [None],  # None is a common decoded-JSON value; must be
            # rejected the same as any other non-str item
        ],
    )
    def test_malformed_permissions_shape_raises(
        self, keypair, settings, malformed_permissions
    ):
        private_key, _public_key = keypair
        token = _make_token(private_key, permissions=malformed_permissions)

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    def test_empty_permissions_list_is_valid(self, keypair, settings):
        """An empty list is a legitimate value (e.g. a suspended
        membership's effective permissions), distinct from a
        malformed one — must NOT be rejected."""
        private_key, _public_key = keypair
        token = _make_token(private_key, permissions=[])

        claims = TokenVerifier(settings).verify(token)

        assert claims.permissions == frozenset()

    def test_duplicate_permissions_are_canonicalized(self, keypair, settings):
        """Not because duplicates are expected on a real token, but
        because frozenset() intentionally canonicalizes them — this
        documents that as actual behavior, not an accident."""
        private_key, _public_key = keypair
        token = _make_token(private_key, permissions=["clients:read", "clients:read"])

        claims = TokenVerifier(settings).verify(token)

        assert claims.permissions == frozenset({"clients:read"})

    def test_permissions_containing_an_unrecognized_string_is_still_accepted(
        self, keypair, settings
    ):
        """Amendment 4's additive-claim-evolution compatibility rule:
        a permissions list may legitimately contain permission strings
        belonging to another service's domain (e.g. jobs:write, once
        job-service exists) — client-service must accept the token and
        simply not find that permission relevant, never reject the
        token outright for containing something it doesn't recognize."""
        private_key, _public_key = keypair
        token = _make_token(
            private_key, permissions=["clients:read", "jobs:write", "invoices:approve"]
        )

        claims = TokenVerifier(settings).verify(token)

        assert "clients:read" in claims.permissions
        assert "jobs:write" in claims.permissions

    @pytest.mark.parametrize("field", ["sub", "tenant_id", "jti"])
    def test_malformed_uuid_claim_raises(self, keypair, settings, field):
        private_key, _public_key = keypair
        token = _make_token(private_key, **{field: "not-a-valid-uuid"})

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    @pytest.mark.parametrize(
        "malformed_value",
        [
            "abc",  # non-numeric string
            "1",  # numeric-LOOKING string — must still be rejected;
            # JWT wire representation must be a JSON integer,
            # not a string Pydantic would happily coerce.
            True,  # bool — bool is an int subclass in Python, so
            # isinstance(True, int) is True; type(True) is int
            # is False, which is exactly why the production
            # check uses type() is, not isinstance().
            [1],  # wrong shape entirely
        ],
    )
    def test_malformed_permissions_version_raises(
        self, keypair, settings, malformed_value
    ):
        """Completes the application-claim validation story alongside
        the UUID and permissions-shape cases above — permissions_version
        must be a genuine JSON integer; anything else, including a
        numeric-looking string or a bool, must be rejected rather than
        silently coerced."""
        private_key, _public_key = keypair
        token = _make_token(private_key, permissions_version=malformed_value)

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)

    @pytest.mark.parametrize(
        "malformed_value", [123, ["owner"], {"role": "owner"}, True]
    )
    def test_malformed_role_raises(self, keypair, settings, malformed_value):
        private_key, _public_key = keypair
        token = _make_token(private_key, role=malformed_value)

        with pytest.raises(InvalidAccessTokenError):
            TokenVerifier(settings).verify(token)


class TestJWKSCaching:
    def test_multiple_verifications_reuse_cached_jwks(
        self, keypair, settings, jwks_server
    ):
        """Platform Conventions §7: no per-request callback to
        identity-service for verification. Proves it directly by
        counting real HTTP requests the local JWKS server actually
        received, not by assuming PyJWKClient's cache_keys=True works."""
        private_key, _public_key = keypair
        verifier = TokenVerifier(settings)

        for _ in range(5):
            token = _make_token(private_key)
            verifier.verify(token)

        assert jwks_server.request_count == 1
