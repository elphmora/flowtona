"""
app/security/hashing.py

Two clearly separate concerns, deliberately not one generic hash_secret()
function — the threat models are different:

- Passwords: low-entropy, human-chosen secrets. Argon2id is deliberately
  slow (memory-hard + time-hard) to resist brute-forcing. Output is
  non-deterministic (random salt per call) — you never look a password
  up BY its hash, you verify a candidate against a known hash.

- Tokens (refresh tokens, invite tokens, email-verification tokens):
  already high-entropy random strings (see generate_secure_token()
  below). Hashing them with argon2id would be pointlessly slow AND
  functionally wrong — every repository looks records up BY token_hash
  as a dict key (refresh_token_id_by_hash, invitation_id_by_token_hash,
  etc.), which requires a DETERMINISTIC hash. SHA-256 is the correct,
  standard choice here: fast, deterministic, and the input is already
  high-entropy so slow-hashing buys nothing.

Argon2id cost parameters are configurable (Decision 7 — not hardcoded),
sourced from Settings. See app/core/config.py's ARGON2_* fields.
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError

from app.core.config import settings

_password_hasher = PasswordHasher(
    time_cost=settings.ARGON2_TIME_COST,
    memory_cost=settings.ARGON2_MEMORY_COST_KIB,
    parallelism=settings.ARGON2_PARALLELISM,
)


def hash_password(password: str) -> str:
    """Argon2id, cost parameters from Settings. Output is a self-describing
    encoded string (includes the algorithm, parameters, and salt) — safe
    to store directly, nothing else needs to be persisted alongside it."""
    return _password_hasher.hash(password)


def verify_password(*, password: str, password_hash: str) -> bool:
    """Returns a plain bool — callers don't need to distinguish "wrong
    password" from "corrupted/malformed stored hash"; both mean this
    password doesn't verify against what's stored."""
    try:
        _password_hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHash):
        return False


def generate_secure_token(*, length_bytes: int = 32) -> str:
    """High-entropy, URL-safe random token — the raw credential handed to
    a caller for delivery (email link, etc.), never persisted directly.
    Only hash_token()'s output is ever stored."""
    return secrets.token_urlsafe(length_bytes)


def hash_token(token: str) -> str:
    """SHA-256, deterministic by design — see module docstring for why
    this must NOT be argon2id. Callers store this, and look records up
    by it; the raw token itself is never persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
