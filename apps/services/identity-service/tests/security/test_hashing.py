"""tests/security/test_hashing.py

Mandatory security test category (Decision 16).
"""

from app.security.hashing import (
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_the_plaintext(self):
        password = "correct horse battery staple"
        hashed = hash_password(password)
        assert hashed != password

    def test_hash_is_non_deterministic(self):
        """Argon2id salts each hash — same password, different output
        every call. This is intentional: never compare hashes by
        equality, always verify_password()."""
        password = "correct horse battery staple"
        assert hash_password(password) != hash_password(password)

    def test_verify_password_true_for_correct_password(self):
        password = "correct horse battery staple"
        hashed = hash_password(password)
        assert verify_password(password=password, password_hash=hashed) is True

    def test_verify_password_false_for_incorrect_password(self):
        hashed = hash_password("correct horse battery staple")
        assert verify_password(password="wrong password", password_hash=hashed) is False

    def test_verify_password_false_for_malformed_hash(self):
        """A corrupted/garbage stored hash must fail closed (return
        False), never raise — callers shouldn't need to distinguish
        "wrong password" from "invalid stored hash"."""
        result = verify_password(
            password="anything", password_hash="not-a-real-argon2-hash"
        )
        assert result is False


class TestTokenHashing:
    def test_hash_token_is_deterministic(self):
        """Unlike passwords, token hashing MUST be deterministic —
        repositories look records up by this hash as a dict key."""
        token = "some-raw-token-value"
        assert hash_token(token) == hash_token(token)

    def test_hash_token_differs_for_different_input(self):
        assert hash_token("token-a") != hash_token("token-b")

    def test_hash_token_is_not_argon2(self):
        """Guards the actual design decision: token hashes must be fast/
        deterministic (SHA-256), not slow/salted (argon2id) — an argon2
        hash of the same input differs every call, so this would fail
        if hash_token were accidentally wired to argon2id instead."""
        token = "some-raw-token-value"
        assert hash_token(token) == hash_token(token)  # deterministic
        assert len(hash_token(token)) == 64  # SHA-256 hex digest length


class TestTokenGeneration:
    def test_generates_different_tokens(self):
        assert generate_secure_token() != generate_secure_token()

    def test_generated_token_is_reasonably_long(self):
        token = generate_secure_token(length_bytes=32)
        assert (
            len(token) >= 32
        )  # base64url encoding of 32 bytes is longer than 32 chars

    def test_generated_token_is_url_safe(self):
        token = generate_secure_token()
        unsafe_chars = {"+", "/", "="}
        assert not any(c in token for c in unsafe_chars)
