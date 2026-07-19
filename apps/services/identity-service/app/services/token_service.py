"""
app/services/token_service.py

Owns SecretProvider access, key caching, and JWT claims-shape
decisions — access tokens (Decision 4) and tenant-selection pre-auth
tokens (Decision 3) are both JWTs but with different claims shapes and
lifetimes; this service is what knows the difference. app/security/jwt.py
stays a stateless signing/verification primitive with no opinion on
either.

Keys are cached as PARSED objects (EllipticCurvePrivateKey/PublicKey),
not just raw bytes, since PyJWT re-parses PEM bytes internally on
every call otherwise. Caching happens lazily on first call, not at
construction time — SecretProvider is async but Python constructors
can't be, and there's no application startup sequence yet to hook an
eager load into.

Loaded keys are validated on two axes: curve (must be P-256 — ES256
specifically means ECDSA over P-256; a P-384 key is still a valid
EllipticCurvePrivateKey and would otherwise pass silently) and, once
both halves are loaded, that they actually form a matching pair.
Mismatched keys loaded independently from separate files would
otherwise let token issuance and JWKS publication both succeed while
every issued token quietly fails verification — a failure mode that's
expensive to diagnose and cheap to catch here instead.

Both token types carry an explicit "token_type" claim, checked
explicitly in both verify methods — the two token types share issuer,
audience, and algorithm, so a validly-signed token of the wrong type
must not be silently accepted by the wrong verify method.

Expired credentials are a distinct exception from malformed/invalid
ones, for both token types — the correct recovery action differs (use
the refresh token vs. re-authenticate from scratch), so collapsing
them into one generic error would lose information the caller needs.

Claims are mapped manually from the raw decoded dict, not via
AccessTokenClaims.model_validate(raw_claims) directly — the raw dict
also carries iss/aud/iat/exp (already verified by decode_jwt(), not
needed by callers) and uses JWT-spec abbreviations (sub) rather than
readable names. Manual mapping keeps the model itself minimal and
readable for every downstream caller.

KNOWN GAP: the pre-auth token's single-use requirement is NOT enforced
by this service. A JWT is stateless by design; enforcing "used once"
needs a tracking store this service deliberately doesn't own — left
for whichever future work builds the tenant-selection flow that needs
it. Do not treat the pre-auth token as single-use until that state
exists; today it is only short-lived.

PHASE 1: exactly one signing key. decode_jwt() accepts
public_keys_by_id (plural) at the primitive level, so the verification
path is already rotation-ready — but this service only ever loads and
caches ONE public key, constructing a single-entry dict on every call.
Multiple concurrently-valid verification keys will be introduced when
signing-key rotation is actually implemented; until then, don't assume
multi-key verification works just because the primitive's signature
accepts a map.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)

from app.constants.roles import Role
from app.core.config import settings
from app.exceptions.token import (
    ExpiredAccessTokenError,
    ExpiredPreauthTokenError,
    InvalidAccessTokenError,
    InvalidPreauthTokenError,
)
from app.security.jwt import build_jwk, decode_jwt, encode_jwt
from app.security.secret_provider import SecretProvider
from app.security.token_models import AccessTokenClaims, PreauthTokenClaims

_ACCESS_TOKEN_TYPE = "access"
_PREAUTH_TOKEN_TYPE = "preauth"


def _require_str_claim(raw_claims: dict[str, object], key: str) -> str:
    """Extract and validate a claim as str. decode_jwt() returns
    dict[str, object] deliberately — a JWT's claim VALUES aren't
    guaranteed any particular type just because the outer JWT-standard
    claims (exp, iss, aud, etc.) have been verified; this project's
    own application-specific claims (sub, role, etc.) still need their
    own explicit type check before use. Raises KeyError (caught
    alongside ValueError at each call site) if the claim is missing or
    the wrong type — not a silent implicit trust that it happens to be
    a string."""
    value = raw_claims.get(key)
    if not isinstance(value, str):
        raise KeyError(key)
    return value


def _require_int_claim(raw_claims: dict[str, object], key: str) -> int:
    value = raw_claims.get(key)
    if not isinstance(value, int):
        raise KeyError(key)
    return value


class TokenService:
    def __init__(self, secret_provider: SecretProvider) -> None:
        self._secret_provider = secret_provider
        self._private_key: EllipticCurvePrivateKey | None = None
        self._public_key: EllipticCurvePublicKey | None = None

    def _validate_keypair_if_loaded(self) -> None:
        """No-op until both keys have been loaded — validation occurs
        immediately after whichever key is loaded second, whether
        that's triggered by an issue_*, verify_*, or build_jwks() call.
        Not a startup-time check (no eager loading, see module
        docstring); the exact moment this fires depends on which
        operation happens to be called first in a given process."""
        if self._private_key is None or self._public_key is None:
            return
        if (
            self._private_key.public_key().public_numbers()
            != self._public_key.public_numbers()
        ):
            raise ValueError(
                "JWT signing private and public keys do not form a matching keypair"
            )

    async def _get_private_key(self) -> EllipticCurvePrivateKey:
        if self._private_key is None:
            pem = await self._secret_provider.get_secret(name="jwt_signing_private_key")
            key = serialization.load_pem_private_key(pem, password=None)
            if not isinstance(key, EllipticCurvePrivateKey):
                raise ValueError("jwt_signing_private_key is not an EC private key")
            if not isinstance(key.curve, ec.SECP256R1):
                raise ValueError("jwt_signing_private_key must use the P-256 curve")
            self._private_key = key
            self._validate_keypair_if_loaded()
        return self._private_key

    async def _get_public_key(self) -> EllipticCurvePublicKey:
        if self._public_key is None:
            pem = await self._secret_provider.get_secret(name="jwt_signing_public_key")
            key = serialization.load_pem_public_key(pem)
            if not isinstance(key, EllipticCurvePublicKey):
                raise ValueError("jwt_signing_public_key is not an EC public key")
            if not isinstance(key.curve, ec.SECP256R1):
                raise ValueError("jwt_signing_public_key must use the P-256 curve")
            self._public_key = key
            self._validate_keypair_if_loaded()
        return self._public_key

    async def issue_access_token(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role: Role,
        permissions_version: int,
    ) -> str:
        now = datetime.now(timezone.utc)
        claims = {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": role.value,
            "permissions_version": permissions_version,
            "token_type": _ACCESS_TOKEN_TYPE,
            "jti": str(uuid4()),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        }
        private_key = await self._get_private_key()
        return encode_jwt(
            claims, private_key=private_key, key_id=settings.JWT_SIGNING_KEY_ID
        )

    async def verify_access_token(self, *, token: str) -> AccessTokenClaims:
        public_key = await self._get_public_key()
        try:
            raw_claims = decode_jwt(
                token,
                public_keys_by_id={settings.JWT_SIGNING_KEY_ID: public_key},
                issuer=settings.JWT_ISSUER,
                audience=settings.JWT_AUDIENCE,
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise ExpiredAccessTokenError() from exc
        except pyjwt.PyJWTError as exc:
            raise InvalidAccessTokenError() from exc

        if raw_claims.get("token_type") != _ACCESS_TOKEN_TYPE:
            raise InvalidAccessTokenError()

        try:
            return AccessTokenClaims(
                user_id=UUID(_require_str_claim(raw_claims, "sub")),
                tenant_id=UUID(_require_str_claim(raw_claims, "tenant_id")),
                role=Role(_require_str_claim(raw_claims, "role")),
                permissions_version=_require_int_claim(
                    raw_claims, "permissions_version"
                ),
                jti=UUID(_require_str_claim(raw_claims, "jti")),
            )
        except (KeyError, ValueError) as exc:
            raise InvalidAccessTokenError() from exc

    async def issue_preauth_token(self, *, user_id: UUID) -> str:
        now = datetime.now(timezone.utc)
        claims = {
            "sub": str(user_id),
            "token_type": _PREAUTH_TOKEN_TYPE,
            "jti": str(uuid4()),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(seconds=settings.PREAUTH_TOKEN_EXPIRE_SECONDS),
        }
        private_key = await self._get_private_key()
        return encode_jwt(
            claims, private_key=private_key, key_id=settings.JWT_SIGNING_KEY_ID
        )

    async def verify_preauth_token(self, *, token: str) -> PreauthTokenClaims:
        public_key = await self._get_public_key()
        try:
            raw_claims = decode_jwt(
                token,
                public_keys_by_id={settings.JWT_SIGNING_KEY_ID: public_key},
                issuer=settings.JWT_ISSUER,
                audience=settings.JWT_AUDIENCE,
            )
        except pyjwt.ExpiredSignatureError as exc:
            raise ExpiredPreauthTokenError() from exc
        except pyjwt.PyJWTError as exc:
            raise InvalidPreauthTokenError() from exc

        if raw_claims.get("token_type") != _PREAUTH_TOKEN_TYPE:
            raise InvalidPreauthTokenError()

        try:
            return PreauthTokenClaims(
                user_id=UUID(_require_str_claim(raw_claims, "sub")),
                jti=UUID(_require_str_claim(raw_claims, "jti")),
            )
        except (KeyError, ValueError) as exc:
            raise InvalidPreauthTokenError() from exc

    async def build_jwks(self) -> dict[str, object]:
        public_key = await self._get_public_key()
        jwk = build_jwk(public_key, key_id=settings.JWT_SIGNING_KEY_ID)
        return {"keys": [jwk]}
