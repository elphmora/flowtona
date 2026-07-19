"""tests/security/test_generate_signing_keypair.py

Tests for scripts/generate_signing_keypair.py — the key generation
script this project's SecretProvider deliberately doesn't do itself
(see secret_provider.py's module docstring).
"""

import stat
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from scripts.generate_signing_keypair import generate_keypair


class TestGenerateKeypair:
    def test_creates_both_files(self, tmp_path):
        generate_keypair(tmp_path)

        assert (tmp_path / "jwt_signing_private_key.pem").exists()
        assert (tmp_path / "jwt_signing_public_key.pem").exists()

    def test_generates_p256_elliptic_curve_keypair(self, tmp_path):
        """Decision 4 specifically requires ES256 / P-256 — proving the
        files merely parse and match each other isn't enough, since a
        different (still internally-consistent) key type or curve
        would also satisfy those weaker checks."""
        generate_keypair(tmp_path)

        private_key = serialization.load_pem_private_key(
            (tmp_path / "jwt_signing_private_key.pem").read_bytes(),
            password=None,
        )
        public_key = serialization.load_pem_public_key(
            (tmp_path / "jwt_signing_public_key.pem").read_bytes()
        )

        assert isinstance(private_key, ec.EllipticCurvePrivateKey)
        assert isinstance(public_key, ec.EllipticCurvePublicKey)
        assert isinstance(private_key.curve, ec.SECP256R1)
        assert isinstance(public_key.curve, ec.SECP256R1)

    def test_generated_public_key_matches_private_key(self, tmp_path):
        generate_keypair(tmp_path)

        private_key = serialization.load_pem_private_key(
            (tmp_path / "jwt_signing_private_key.pem").read_bytes(),
            password=None,
        )
        public_key = serialization.load_pem_public_key(
            (tmp_path / "jwt_signing_public_key.pem").read_bytes()
        )

        assert isinstance(private_key, ec.EllipticCurvePrivateKey)
        assert isinstance(public_key, ec.EllipticCurvePublicKey)
        assert private_key.public_key().public_numbers() == public_key.public_numbers()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
    def test_private_key_has_restrictive_permissions(self, tmp_path):
        generate_keypair(tmp_path)

        mode = stat.S_IMODE((tmp_path / "jwt_signing_private_key.pem").stat().st_mode)
        assert mode == 0o600

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
    def test_public_key_has_readable_permissions(self, tmp_path):
        generate_keypair(tmp_path)

        mode = stat.S_IMODE((tmp_path / "jwt_signing_public_key.pem").stat().st_mode)
        assert mode == 0o644

    def test_refuses_to_overwrite_existing_keys_by_default(self, tmp_path):
        generate_keypair(tmp_path)
        private_path = tmp_path / "jwt_signing_private_key.pem"
        public_path = tmp_path / "jwt_signing_public_key.pem"
        original_private = private_path.read_bytes()
        original_public = public_path.read_bytes()

        with pytest.raises(FileExistsError):
            generate_keypair(tmp_path)

        assert private_path.read_bytes() == original_private
        assert public_path.read_bytes() == original_public

    def test_force_permits_intentional_replacement(self, tmp_path):
        generate_keypair(tmp_path)
        original_private = (tmp_path / "jwt_signing_private_key.pem").read_bytes()

        generate_keypair(tmp_path, force=True)

        new_private = (tmp_path / "jwt_signing_private_key.pem").read_bytes()
        assert new_private != original_private

    def test_custom_secrets_directory_is_created(self, tmp_path):
        custom_dir = tmp_path / "nested" / "secrets"
        generate_keypair(custom_dir)

        assert (custom_dir / "jwt_signing_private_key.pem").exists()
