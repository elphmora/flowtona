"""
app/security/secret_provider.py

SecretProvider abstraction (Decision 14) — decouples identity-service
from any specific secrets backend. A generic get_secret(name) -> bytes
interface, not JWT-specific methods — stays useful for whatever future
secrets this service needs beyond the JWT signing keypair, which is
all it's used for today. Callers interpret what they get back (parse
PEM, etc.); this provider never parses or validates content, just
fetches it by name.

Returns bytes, not str — PEM files are byte-oriented cryptographic
material, and cryptography.hazmat's load_pem_private_key()/
load_pem_public_key() both take bytes directly. Returning str would
force jwt.py into an unnecessary decode-then-re-encode round trip for
no benefit, and risks silently mangling content via implicit text
decoding or newline translation.

Secret names are restricted to a safe character set (_SECRET_NAME_PATTERN)
— even though every current caller supplies a hardcoded literal name,
this boundary enforces its own invariant rather than trusting callers,
matching the defensive-validation pattern used at other boundaries in
this codebase (e.g. User.update() rejecting email changes). Without
this, a name like "../../other-secret" would escape secrets_dir
entirely via path traversal.

FileSecretProvider is the Phase 1 local-dev implementation: reads
plain files from a directory, one file per secret. A future AWS
Secrets Manager (or similar) implementation would satisfy the same
Protocol with network calls instead of file reads — jwt.py and
anything else using SecretProvider never needs to change when that
swap happens; only how this class is constructed changes.

Async despite local file reads being synchronous and technically
blocking the event loop briefly: for tiny local PEM files that's
negligible, and keeping the Protocol async now avoids a breaking
signature change whenever a real network-backed provider (AWS Secrets
Manager) is eventually added. Not worth thread-offloading two small
local reads for.

Key GENERATION is deliberately NOT this provider's job — see
scripts/generate_signing_keypair.py. This provider only reads what's
already there; a missing secret is a deployment/configuration problem,
not something this class should paper over by generating one on the
fly.
"""

import re
from pathlib import Path
from typing import Protocol

_SECRET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class SecretProviderError(RuntimeError):
    """Base for all secret-retrieval failures. An infrastructure/
    deployment configuration problem category, not a business-rule
    violation — deliberately NOT a DomainError, not routed through the
    RFC 9457 pipeline. A missing or unreadable signing key means the
    service cannot function at all; this is expected to crash startup,
    not be caught per-request."""


class InvalidSecretNameError(SecretProviderError):
    def __init__(self, *, name: str) -> None:
        self.name = name
        super().__init__(f"Invalid secret name: {name!r}")


class SecretNotFoundError(SecretProviderError):
    def __init__(self, *, name: str) -> None:
        self.name = name
        super().__init__(f"Secret {name!r} was not found")


class SecretReadError(SecretProviderError):
    """The secret exists but couldn't be read — wrong permissions, the
    path is a directory, or another OS-level failure. Distinct from
    SecretNotFoundError: this is a different failure category (the
    secret IS there, something else is wrong) that a caller or
    operator would want to diagnose differently."""

    def __init__(self, *, name: str) -> None:
        self.name = name
        super().__init__(f"Secret {name!r} could not be read")


class EmptySecretError(SecretProviderError):
    def __init__(self, *, name: str) -> None:
        self.name = name
        super().__init__(f"Secret {name!r} is empty")


class SecretProvider(Protocol):
    async def get_secret(self, *, name: str) -> bytes:
        """Return uninterpreted secret material by logical name.
        Raises SecretNotFoundError, SecretReadError, EmptySecretError,
        or InvalidSecretNameError as appropriate."""
        ...


class FileSecretProvider:
    """Local-dev implementation: reads plain files from a directory,
    one file per secret, filename derived from the logical secret name
    (see _path_for). Never commit real key material — the secrets
    directory must be gitignored."""

    def __init__(self, *, secrets_dir: Path) -> None:
        self._secrets_dir = secrets_dir

    def _path_for(self, name: str) -> Path:
        if not _SECRET_NAME_PATTERN.fullmatch(name):
            raise InvalidSecretNameError(name=name)
        # .pem suffix is a FILE-specific detail, kept out of the
        # logical secret name so the Protocol's `name` parameter stays
        # free of any one backend's formatting assumptions.
        return self._secrets_dir / f"{name}.pem"

    async def get_secret(self, *, name: str) -> bytes:
        path = self._path_for(name)

        # Read directly rather than checking existence first — avoids
        # the TOCTOU race where the file could vanish between an
        # exists() check and the actual read.
        try:
            content = path.read_bytes()
        except FileNotFoundError as exc:
            raise SecretNotFoundError(name=name) from exc
        except OSError as exc:
            # Covers IsADirectoryError, PermissionError, and any other
            # OS-level read failure — all "the secret exists but
            # couldn't be read," a different category from not found.
            raise SecretReadError(name=name) from exc

        if not content:
            raise EmptySecretError(name=name)

        return content
