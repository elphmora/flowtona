#!/usr/bin/env python3
"""
scripts/generate_signing_keypair.py

One-time (or per-rotation) local dev setup: generates an EC P-256
keypair for JWT signing (ES256, Decision 4) and writes it as PEM files
into the secrets directory FileSecretProvider reads from.

Deliberately a separate script, not something SecretProvider does
itself — key generation is a setup/rotation concern, not something a
read-only secret-fetching abstraction should paper over by silently
generating one on first use (see SecretProvider's module docstring).

Refuses to overwrite an existing keypair by default — accidentally
rerunning this against a directory with a live signing key would
replace the signing identity and invalidate every existing token.
Pass --force for an intentional rotation.

Usage:
    python scripts/generate_signing_keypair.py [--secrets-dir PATH] [--force]

Writes:
    <secrets-dir>/jwt_signing_private_key.pem  (chmod 0600)
    <secrets-dir>/jwt_signing_public_key.pem   (chmod 0644)
"""

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

DEFAULT_SECRETS_DIR = Path(".flowtona/secrets")


def generate_keypair(secrets_dir: Path, *, force: bool = False) -> None:
    secrets_dir.mkdir(parents=True, exist_ok=True)

    private_path = secrets_dir / "jwt_signing_private_key.pem"
    public_path = secrets_dir / "jwt_signing_public_key.pem"

    existing = [p for p in (private_path, public_path) if p.exists()]
    if existing and not force:
        names = ", ".join(str(p) for p in existing)
        raise FileExistsError(
            f"Refusing to overwrite existing signing key material: {names}. "
            "Pass --force for an intentional rotation."
        )

    # P-256 — matches ES256 (Decision 4), the same curve already shown
    # in 01-api-contract.md's JWKS example ("kty": "EC", "crv": "P-256").
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_pem)
    private_path.chmod(0o600)

    public_path.write_bytes(public_pem)
    public_path.chmod(0o644)

    print(f"Generated ES256 (P-256) signing keypair in {secrets_dir}/")
    print(f"  {private_path.name}  (0600)")
    print(f"  {public_path.name}  (0644)")
    print()
    print("Never commit these files — confirm they're covered by .gitignore.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secrets-dir",
        type=Path,
        default=DEFAULT_SECRETS_DIR,
        help=f"Directory to write the keypair into (default: {DEFAULT_SECRETS_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing local signing keypair.",
    )
    args = parser.parse_args()
    generate_keypair(args.secrets_dir, force=args.force)


if __name__ == "__main__":
    main()
