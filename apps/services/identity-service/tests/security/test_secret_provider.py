"""tests/security/test_secret_provider.py

Mandatory security test category (Decision 16).
"""

import pytest

from app.security.secret_provider import (
    EmptySecretError,
    FileSecretProvider,
    InvalidSecretNameError,
    SecretNotFoundError,
    SecretReadError,
)

pytestmark = pytest.mark.asyncio


class TestFileSecretProvider:
    async def test_returns_bytes_for_existing_secret(self, tmp_path):
        (tmp_path / "my_secret.pem").write_bytes(b"-----BEGIN FAKE-----\ncontent\n")
        provider = FileSecretProvider(secrets_dir=tmp_path)

        result = await provider.get_secret(name="my_secret")

        assert isinstance(result, bytes)
        assert result == b"-----BEGIN FAKE-----\ncontent\n"

    async def test_raises_not_found_for_missing_secret(self, tmp_path):
        provider = FileSecretProvider(secrets_dir=tmp_path)

        with pytest.raises(SecretNotFoundError) as exc_info:
            await provider.get_secret(name="never-existed")

        assert exc_info.value.name == "never-existed"

    async def test_secret_name_does_not_need_pem_extension(self, tmp_path):
        """Confirms the .pem suffix is an implementation detail of
        FileSecretProvider, not something callers need to know about —
        the logical secret name stays clean."""
        (tmp_path / "jwt_signing_private_key.pem").write_bytes(b"key-material")
        provider = FileSecretProvider(secrets_dir=tmp_path)

        result = await provider.get_secret(name="jwt_signing_private_key")

        assert result == b"key-material"

    async def test_does_not_generate_a_missing_secret(self, tmp_path):
        """Confirms the provider is read-only — a missing secret must
        raise, never silently create one."""
        provider = FileSecretProvider(secrets_dir=tmp_path)

        with pytest.raises(SecretNotFoundError):
            await provider.get_secret(name="some_secret")

        assert list(tmp_path.iterdir()) == []

    async def test_raises_empty_secret_error_for_empty_file(self, tmp_path):
        (tmp_path / "empty_secret.pem").write_bytes(b"")
        provider = FileSecretProvider(secrets_dir=tmp_path)

        with pytest.raises(EmptySecretError) as exc_info:
            await provider.get_secret(name="empty_secret")

        assert exc_info.value.name == "empty_secret"

    async def test_raises_read_error_when_path_is_a_directory(self, tmp_path):
        """A name that happens to resolve to a directory (not a file)
        is a distinct failure category from 'not found' — the secret
        conceptually exists at that path, something else is wrong."""
        (tmp_path / "a_directory.pem").mkdir()
        provider = FileSecretProvider(secrets_dir=tmp_path)

        with pytest.raises(SecretReadError) as exc_info:
            await provider.get_secret(name="a_directory")

        assert exc_info.value.name == "a_directory"

    @pytest.mark.parametrize(
        "bad_name",
        [
            "../../etc/passwd",
            "../escape",
            "name/with/slashes",
            "",
            "-starts-with-dash",
            "has spaces",
        ],
    )
    async def test_rejects_unsafe_secret_names(self, tmp_path, bad_name):
        """Guards the path-traversal boundary directly — a malformed
        or malicious name must never reach the filesystem layer at
        all, regardless of what does or doesn't exist on disk."""
        provider = FileSecretProvider(secrets_dir=tmp_path)

        with pytest.raises(InvalidSecretNameError):
            await provider.get_secret(name=bad_name)

    async def test_accepts_names_with_underscores_and_hyphens(self, tmp_path):
        (tmp_path / "valid-name_123.pem").write_bytes(b"content")
        provider = FileSecretProvider(secrets_dir=tmp_path)

        result = await provider.get_secret(name="valid-name_123")

        assert result == b"content"
