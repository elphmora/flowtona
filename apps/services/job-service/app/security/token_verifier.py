"""
app/security/token_verifier.py

Verifies access tokens issued by identity-service against its
published JWKS (Platform Conventions §7, §13). Ported directly from
client-service's own token_verifier.py -- this is security-critical
code, and the same identity-service issues tokens for every consumer,
so there's no reason for job-service's verification logic to differ.
Only the module path and this docstring's framing changed.

AccessTokenClaims models the application claims retained after JWT
verification -- not the JWT protocol envelope (iss/aud/iat/exp), which
is fully consumed by verification itself and not retained. role and
permissions_version are present for diagnostics/logging; job-service
authorizes exclusively from `permissions`, never from role.

Every failure still collapses to a single InvalidAccessTokenError
externally (401 uniformly, no expired-vs-invalid distinction visible
to any caller). Internally, each failure also increments
JWT_VERIFICATION_FAILURES_TOTAL{reason} before raising -- see
client-service-architecture.md's Entity & Convention Clarifications
for the full reasoning behind each reason category; not re-derived
here since it's identical for job-service.
"""

from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.exceptions.auth import InvalidAccessTokenError
from app.metrics.auth_metrics import JWT_VERIFICATION_FAILURES_TOTAL

_ACCESS_TOKEN_TYPE = "access"


class AccessTokenClaims(BaseModel):
    """The application claims retained by job-service after JWT
    verification -- not the JWT protocol envelope. iss/aud are
    deliberately not modeled: by the time this object exists,
    jwt.decode() has already validated both against configured
    settings. iat/exp are similarly not modeled -- no current consumer
    needs them.

    role and permissions_version MUST NOT be used for authorization
    decisions -- job-service authorizes exclusively from
    `permissions`."""

    sub: UUID
    tenant_id: UUID
    role: str
    permissions: frozenset[str]
    permissions_version: int
    token_type: str
    jti: UUID


class TokenVerifier:
    """Wraps a PyJWKClient bound to identity-service's JWKS endpoint.
    One instance is built once at startup (app/main.py) and reused for
    the process lifetime -- PyJWKClient's own caching depends on being
    reused across calls, not reconstructed per request."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwk_client = PyJWKClient(
            settings.JWKS_URL,
            cache_keys=True,
            lifespan=settings.JWKS_CACHE_TTL_SECONDS,
            timeout=settings.JWKS_FETCH_TIMEOUT_SECONDS,
        )

    def verify(self, raw_token: str) -> AccessTokenClaims:
        """Platform Conventions §7's checklist: signature + algorithm,
        kid resolution, iss, aud, exp, every application claim present
        (enforced via PyJWT's own `require` option), token_type ==
        "access". Raises InvalidAccessTokenError uniformly on any
        failure."""
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(raw_token)
        except jwt.exceptions.InvalidTokenError as exc:
            JWT_VERIFICATION_FAILURES_TOTAL.labels(reason="malformed_token").inc()
            raise InvalidAccessTokenError() from exc
        except jwt.exceptions.PyJWKClientError as exc:
            JWT_VERIFICATION_FAILURES_TOTAL.labels(reason="key_resolution_failed").inc()
            raise InvalidAccessTokenError() from exc

        try:
            payload = jwt.decode(
                raw_token,
                signing_key.key,
                algorithms=[self._settings.JWKS_ALGORITHM],
                issuer=self._settings.JWKS_ISSUER,
                audience=self._settings.JWKS_AUDIENCE,
                options={
                    "require": [
                        "exp",
                        "iss",
                        "aud",
                        "sub",
                        "tenant_id",
                        "role",
                        "permissions",
                        "permissions_version",
                        "token_type",
                        "jti",
                    ]
                },
            )
        except jwt.exceptions.ExpiredSignatureError as exc:
            JWT_VERIFICATION_FAILURES_TOTAL.labels(reason="expired").inc()
            raise InvalidAccessTokenError() from exc
        except jwt.exceptions.InvalidTokenError as exc:
            JWT_VERIFICATION_FAILURES_TOTAL.labels(reason="invalid_claims").inc()
            raise InvalidAccessTokenError() from exc

        if payload.get("token_type") != _ACCESS_TOKEN_TYPE:
            JWT_VERIFICATION_FAILURES_TOTAL.labels(reason="wrong_token_type").inc()
            raise InvalidAccessTokenError()

        return self._build_claims(payload)

    def _build_claims(self, payload: dict[str, Any]) -> AccessTokenClaims:
        """Validate application-claim types and construct the typed
        claims object. PyJWT's `require` option confirms claim
        presence; this method enforces the application-level wire
        types job-service expects."""
        try:
            raw_permissions = payload["permissions"]
            if not isinstance(raw_permissions, list) or not all(
                isinstance(item, str) for item in raw_permissions
            ):
                JWT_VERIFICATION_FAILURES_TOTAL.labels(
                    reason="malformed_application_claims"
                ).inc()
                raise InvalidAccessTokenError()

            raw_role = payload["role"]
            if type(raw_role) is not str:
                JWT_VERIFICATION_FAILURES_TOTAL.labels(
                    reason="malformed_application_claims"
                ).inc()
                raise InvalidAccessTokenError()

            raw_permissions_version = payload["permissions_version"]
            if type(raw_permissions_version) is not int:
                JWT_VERIFICATION_FAILURES_TOTAL.labels(
                    reason="malformed_application_claims"
                ).inc()
                raise InvalidAccessTokenError()

            return AccessTokenClaims(
                sub=payload["sub"],
                tenant_id=payload["tenant_id"],
                role=raw_role,
                permissions=frozenset(raw_permissions),
                permissions_version=raw_permissions_version,
                token_type=payload["token_type"],
                jti=payload["jti"],
            )
        except (KeyError, ValidationError) as exc:
            JWT_VERIFICATION_FAILURES_TOTAL.labels(
                reason="malformed_application_claims"
            ).inc()
            raise InvalidAccessTokenError() from exc
