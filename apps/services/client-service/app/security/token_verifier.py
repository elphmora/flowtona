"""
app/security/token_verifier.py

Verifies access tokens issued by identity-service against its
published JWKS (Platform Conventions §7, §13).

AccessTokenClaims models the application claims retained by
client-service after JWT verification — not the JWT protocol envelope
(iss/aud/iat/exp), which is fully consumed by verification itself and
not retained. role and permissions_version are present for
diagnostics and logging; client-service authorizes exclusively from
`permissions` (Decision 3), never from role.

Design history (why aud is "flowtona-api" and not an earlier guessed
value, why token_type replaced an invented "purpose" mechanism, why
role stays a plain str rather than importing identity-service's Role
enum) is recorded in client-service-architecture.md's Entity &
Convention Clarifications, not here — this file documents current
behavior only.

Every failure still collapses to a single InvalidAccessTokenError
externally — that behavior is UNCHANGED (401 uniformly, no expired-
vs-invalid distinction visible to any caller). Internally, each
failure also increments JWT_VERIFICATION_FAILURES_TOTAL{reason}
(app/metrics/auth_metrics.py) before raising, so the uniform external
contract and richer internal observability coexist without either
compromising the other. Reason values, and why they're grouped the
way they are:

  malformed_token             - token is structurally invalid before
                                 signature verification ever runs
                                 (confirmed: PyJWT raises DecodeError,
                                 an InvalidTokenError subclass, at this
                                 stage for "not enough segments" etc.)
  key_resolution_failed       - PyJWKClientError: unknown kid, or the
                                 JWKS endpoint was unreachable. NOT
                                 split further — PyJWKClientError has
                                 no further public subclass hierarchy
                                 confirmed safe to distinguish by type
                                 (confirmed: its only base is the
                                 generic PyJWTError, a sibling of
                                 InvalidTokenError, not a parent of
                                 further distinguishable subclasses).
  expired                     - ExpiredSignatureError specifically,
                                 caught before the broader
                                 InvalidTokenError below (confirmed: a
                                 genuine InvalidTokenError subclass,
                                 not grouped-by-message-string).
  invalid_claims               - every other InvalidTokenError from
                                 jwt.decode() (wrong issuer, wrong
                                 audience, bad signature, wrong
                                 algorithm, missing required claim).
                                 Deliberately NOT split further per
                                 sub-case — PyJWT's exact subclass for
                                 each was not verified against a real
                                 install for this pass, and grouping
                                 avoids asserting a distinction that
                                 hasn't actually been confirmed.
  wrong_token_type             - token_type claim present and well-
                                 formed, but not "access".
  malformed_application_claims - permissions/role/permissions_version
                                 wire shape wrong, or AccessTokenClaims
                                 construction itself failed (malformed
                                 UUID in sub/tenant_id/jti). All grouped
                                 under one reason since the operational
                                 response is identical regardless of
                                 which specific field was malformed:
                                 identity-service is issuing tokens
                                 that don't match the claim contract.
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
    """The application claims retained by client-service after JWT
    verification — not the JWT protocol envelope. iss/aud are
    deliberately not modeled: by the time this object exists,
    jwt.decode() has already validated both against configured
    settings, so they're tautologically constant on every token this
    verifier accepts and add no diagnostic value modeling them would
    provide. iat/exp are similarly not modeled — no current consumer
    needs them; add them if one does, not speculatively.

    role and permissions_version MUST NOT be used for authorization
    decisions here — client-service authorizes exclusively from
    `permissions` (Decision 3)."""

    sub: UUID
    tenant_id: UUID
    role: str
    permissions: frozenset[str]
    permissions_version: int
    token_type: str
    jti: UUID


class TokenVerifier:
    """Wraps a PyJWKClient bound to identity-service's JWKS endpoint.
    One instance is built once at startup (app/api/dependencies.py)
    and reused for the process lifetime — PyJWKClient's own caching
    depends on being reused across calls, not reconstructed per
    request."""

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
        (enforced via PyJWT's own `require` option, not just checked
        after the fact), token_type == "access". Raises
        InvalidAccessTokenError uniformly on any failure — see module
        docstring for the internal reason categorization this no
        longer discards, even though it stays invisible externally."""
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
        client-service claims object.

        PyJWT's `require` option confirms claim presence; this method
        enforces the application-level wire types expected by
        client-service.
        """
        try:
            raw_permissions = payload["permissions"]
            if not isinstance(raw_permissions, list) or not all(
                isinstance(item, str) for item in raw_permissions
            ):
                # frozenset() on a bare str decomposes it into
                # characters rather than raising — reject the wrong
                # wire shape explicitly instead.
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
            # type(...) is int, not isinstance(...), specifically to
            # exclude bool — bool is an int subclass in Python, so
            # isinstance(True, int) is True; a permissions_version
            # claim of `true`/`false` must be rejected as malformed,
            # not silently accepted as 1/0.
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
            # PyJWT's `require` guarantees presence, not type.
            # Translate any missing claim or Pydantic validation
            # failure into our uniform InvalidAccessTokenError.
            JWT_VERIFICATION_FAILURES_TOTAL.labels(
                reason="malformed_application_claims"
            ).inc()
            raise InvalidAccessTokenError() from exc
