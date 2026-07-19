"""tests/unit/services/test_token_service.py"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.constants.roles import Role
from app.exceptions.token import (
    ExpiredAccessTokenError,
    ExpiredPreauthTokenError,
    InvalidAccessTokenError,
    InvalidPreauthTokenError,
)
from app.security.jwt import encode_jwt
from app.security.secret_provider import FileSecretProvider
from app.services.token_service import TokenService
from scripts.generate_signing_keypair import generate_keypair

pytestmark = pytest.mark.asyncio


class _CountingSecretProvider:
    """Wraps a real FileSecretProvider, counting calls — used to prove
    key caching actually happens, not just trusting it works."""

    def __init__(self, inner: FileSecretProvider) -> None:
        self._inner = inner
        self.call_count = 0

    async def get_secret(self, *, name: str) -> bytes:
        self.call_count += 1
        return await self._inner.get_secret(name=name)


@pytest.fixture
def secret_provider(tmp_path):
    generate_keypair(tmp_path)
    return FileSecretProvider(secrets_dir=tmp_path)


@pytest.fixture
def service(secret_provider) -> TokenService:
    return TokenService(secret_provider)


def _expired_claims(*, token_type: str, **extra) -> dict:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(uuid4()),
        "token_type": token_type,
        "jti": str(uuid4()),
        "iss": "https://identity.flowtona.dev",
        "aud": "flowtona-api",
        "iat": now - timedelta(hours=1),
        "exp": now - timedelta(minutes=1),
    }
    claims.update(extra)
    return claims


class TestAccessToken:
    async def test_issue_and_verify_roundtrip(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        token = await service.issue_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            role=Role.OWNER,
            permissions_version=3,
        )

        claims = await service.verify_access_token(token=token)

        assert claims.user_id == user_id
        assert claims.tenant_id == tenant_id
        assert claims.role == Role.OWNER
        assert claims.permissions_version == 3
        assert claims.jti is not None

    async def test_two_tokens_get_different_jti(self, service):
        user_id, tenant_id = uuid4(), uuid4()
        token1 = await service.issue_access_token(
            user_id=user_id, tenant_id=tenant_id, role=Role.OWNER, permissions_version=0
        )
        token2 = await service.issue_access_token(
            user_id=user_id, tenant_id=tenant_id, role=Role.OWNER, permissions_version=0
        )

        claims1 = await service.verify_access_token(token=token1)
        claims2 = await service.verify_access_token(token=token2)

        assert claims1.jti != claims2.jti

    async def test_malformed_token_raises_invalid(self, service):
        token = await service.issue_access_token(
            user_id=uuid4(), tenant_id=uuid4(), role=Role.OWNER, permissions_version=0
        )
        tampered = token[:-4] + "AAAA"

        with pytest.raises(InvalidAccessTokenError):
            await service.verify_access_token(token=tampered)

    async def test_expired_token_raises_expired(self, service, secret_provider):
        """Expired credentials must remain distinguishable from
        malformed ones because the recovery flow differs: an expired
        access token means use the refresh token; a malformed one means
        re-authenticate from scratch."""
        pem = await secret_provider.get_secret(name="jwt_signing_private_key")
        private_key = serialization.load_pem_private_key(pem, password=None)
        expired_token = encode_jwt(
            _expired_claims(
                token_type="access",
                tenant_id=str(uuid4()),
                role=Role.OWNER.value,
                permissions_version=0,
            ),
            private_key=private_key,
            key_id="flowtona-local-001",
        )

        with pytest.raises(ExpiredAccessTokenError):
            await service.verify_access_token(token=expired_token)

    async def test_rejects_non_ec_private_key(self, tmp_path):
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        (tmp_path / "jwt_signing_private_key.pem").write_bytes(rsa_pem)
        (tmp_path / "jwt_signing_public_key.pem").write_bytes(
            rsa_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        service = TokenService(FileSecretProvider(secrets_dir=tmp_path))

        with pytest.raises(ValueError):
            await service.issue_access_token(
                user_id=uuid4(),
                tenant_id=uuid4(),
                role=Role.OWNER,
                permissions_version=0,
            )

    async def test_rejects_non_p256_curve(self, tmp_path):
        """A P-384 key is a valid EC key but the wrong curve for ES256
        — must be rejected at load time, not silently accepted and
        produce tokens that don't match what JWKS advertises."""
        p384_key = ec.generate_private_key(ec.SECP384R1())
        private_pem = p384_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = p384_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        (tmp_path / "jwt_signing_private_key.pem").write_bytes(private_pem)
        (tmp_path / "jwt_signing_public_key.pem").write_bytes(public_pem)
        service = TokenService(FileSecretProvider(secrets_dir=tmp_path))

        with pytest.raises(ValueError):
            await service.issue_access_token(
                user_id=uuid4(),
                tenant_id=uuid4(),
                role=Role.OWNER,
                permissions_version=0,
            )

    async def test_rejects_mismatched_keypair_when_second_key_is_loaded(self, tmp_path):
        """Private and public keys are loaded from separate files —
        both individually valid P-256 keys, but from different pairs,
        must be caught rather than silently accepted. Undetected, this
        would let token issuance and JWKS publication both succeed
        while every issued token quietly fails verification."""
        pair_a = ec.generate_private_key(ec.SECP256R1())
        pair_b = ec.generate_private_key(ec.SECP256R1())

        private_pem = pair_a.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        mismatched_public_pem = pair_b.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        (tmp_path / "jwt_signing_private_key.pem").write_bytes(private_pem)
        (tmp_path / "jwt_signing_public_key.pem").write_bytes(mismatched_public_pem)
        service = TokenService(FileSecretProvider(secrets_dir=tmp_path))

        await service.issue_access_token(
            user_id=uuid4(), tenant_id=uuid4(), role=Role.OWNER, permissions_version=0
        )
        with pytest.raises(ValueError):
            await service.build_jwks()


class TestPreauthToken:
    async def test_issue_and_verify_roundtrip(self, service):
        user_id = uuid4()
        token = await service.issue_preauth_token(user_id=user_id)

        claims = await service.verify_preauth_token(token=token)

        assert claims.user_id == user_id
        assert claims.jti is not None

    async def test_access_token_rejected_as_preauth_token(self, service):
        access_token = await service.issue_access_token(
            user_id=uuid4(), tenant_id=uuid4(), role=Role.OWNER, permissions_version=0
        )

        with pytest.raises(InvalidPreauthTokenError):
            await service.verify_preauth_token(token=access_token)

    async def test_preauth_token_rejected_as_access_token(self, service):
        preauth_token = await service.issue_preauth_token(user_id=uuid4())

        with pytest.raises(InvalidAccessTokenError):
            await service.verify_access_token(token=preauth_token)

    async def test_expired_preauth_token_raises_expired(self, service, secret_provider):
        pem = await secret_provider.get_secret(name="jwt_signing_private_key")
        private_key = serialization.load_pem_private_key(pem, password=None)
        expired_token = encode_jwt(
            _expired_claims(token_type="preauth"),
            private_key=private_key,
            key_id="flowtona-local-001",
        )

        with pytest.raises(ExpiredPreauthTokenError):
            await service.verify_preauth_token(token=expired_token)


class TestBuildJwks:
    async def test_returns_keys_list_with_one_entry(self, service):
        jwks = await service.build_jwks()

        assert "keys" in jwks
        assert len(jwks["keys"]) == 1
        assert jwks["keys"][0]["kty"] == "EC"
        assert jwks["keys"][0]["kid"] == "flowtona-local-001"


class TestKeyCaching:
    async def test_keys_are_only_fetched_once_across_multiple_calls(self, tmp_path):
        generate_keypair(tmp_path)
        counting_provider = _CountingSecretProvider(
            FileSecretProvider(secrets_dir=tmp_path)
        )
        service = TokenService(counting_provider)

        await service.issue_access_token(
            user_id=uuid4(), tenant_id=uuid4(), role=Role.OWNER, permissions_version=0
        )
        token = await service.issue_access_token(
            user_id=uuid4(), tenant_id=uuid4(), role=Role.OWNER, permissions_version=0
        )
        await service.verify_access_token(token=token)
        await service.build_jwks()

        assert counting_provider.call_count == 2
