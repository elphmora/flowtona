"""
app/security/jwt.py

Stateless JWT primitives — sign, verify, and single-JWK construction.
Accepts PARSED key objects (EllipticCurvePrivateKey/PublicKey), not
raw PEM bytes — PyJWT re-parses PEM bytes internally on every single
encode/decode call if given bytes directly, so accepting parsed
objects lets TokenService cache the parsed key itself, avoiding that
repeated parsing cost on every token issued or verified. TokenService
owns reading, parsing, and caching; this module only signs/verifies
what it's handed.

Genuinely stateless, not "pure" — signing/verification still depend on
cryptographic library internals and whatever timestamps the caller
puts in the claims dict — but this module holds no state of its own
between calls. No SecretProvider awareness, no Settings access, no
opinion on claims shape (access token vs. pre-auth token) — TokenService
owns all of that.

PyJWT's own exceptions propagate from decode_jwt() — TokenService
catches and translates them into domain exceptions, matching the
repository -> service exception-translation pattern used elsewhere in
this codebase. The kid lookup below raises pyjwt.InvalidTokenError
(not a bare KeyError) specifically so TokenService's exception
handling stays entirely PyJWT-focused — a malformed kid header (e.g.
a list instead of a string) must fail cleanly through the same path
as any other invalid token, not escape as an unhandled TypeError from
a dict membership check on an unhashable value.

decode_jwt() takes public_keys_by_id (a dict), not a single key — even
with exactly one signing key today, this means an unrecognized kid is
caught explicitly rather than blindly trying the one key regardless of
what the token claims to be signed with, and adding a second
verification key later (rotation) needs no signature change here.
"""

import base64
from collections.abc import Mapping

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)

ALGORITHM = "ES256"

# This project's baseline required claims — every token type issued
# here carries all of these; type-specific claims (tenant_id, role,
# etc.) are validated separately by the claims model TokenService
# constructs from the verified result.
_REQUIRED_CLAIMS = ("sub", "iss", "aud", "iat", "exp", "token_type", "jti")


def encode_jwt(
    claims: Mapping[str, object], *, private_key: EllipticCurvePrivateKey, key_id: str
) -> str:
    """Sign a claims dict with ES256. Caller owns the claims' shape and
    values — this function just signs whatever mapping it's given, and
    never mutates it (Mapping, not dict, makes that explicit)."""
    return pyjwt.encode(
        dict(claims),
        private_key,
        algorithm=ALGORITHM,
        headers={"kid": key_id},
    )


def decode_jwt(
    token: str,
    *,
    public_keys_by_id: dict[str, EllipticCurvePublicKey],
    issuer: str,
    audience: str,
) -> dict[str, object]:
    """Verify signature + standard claims (exp, iss, aud) + presence of
    this project's baseline required claims. Looks up the verification
    key by the token's own kid header. Returns the raw claims dict;
    TokenService validates it into a typed model. Algorithm is always
    pinned to ES256 (module constant, not derived from the token's own
    header) — never let the token choose its own verification
    algorithm."""
    header = pyjwt.get_unverified_header(token)
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise pyjwt.InvalidTokenError("Missing or invalid kid header")

    try:
        public_key = public_keys_by_id[kid]
    except KeyError as exc:
        raise pyjwt.InvalidTokenError("Unrecognized kid header") from exc

    return pyjwt.decode(
        token,
        public_key,
        algorithms=[ALGORITHM],
        issuer=issuer,
        audience=audience,
        options={"require": list(_REQUIRED_CLAIMS)},
    )


def build_jwk(public_key: EllipticCurvePublicKey, *, key_id: str) -> dict[str, object]:
    """Convert a P-256 EC public key into a single JWK dict, for
    assembly into a JWKS {"keys": [...]} response — TokenService's job,
    not this function's; this only builds ONE key entry. Rejects any
    non-EC key and any curve other than P-256, since the returned JWK
    always advertises "crv": "P-256" / "alg": "ES256" regardless of
    what key it's actually given — a defensive check at this boundary,
    not just relying on the type hint, since jwt.py is meant to work
    as a standalone primitive independent of whatever caller-side
    validation TokenService happens to do before calling this."""
    if not isinstance(public_key, EllipticCurvePublicKey):
        raise ValueError("build_jwk() requires an EC public key")
    if not isinstance(public_key.curve, ec.SECP256R1):
        raise ValueError("build_jwk() requires a P-256 public key")

    numbers = public_key.public_numbers()
    # P-256 coordinates are always 32 bytes — pad explicitly rather
    # than relying on to_bytes() to infer the right length.
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
