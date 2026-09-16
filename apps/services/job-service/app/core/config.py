"""
app/core/config.py

job-service configuration.

ERROR_BASE_URI added this checkpoint, with the exact field_validator
ported from client-service's own confirmed Settings -- app/exceptions/
base.py previously hardcoded this as a module constant
(PROBLEM_BASE_URI), a real divergence from client-service's pattern of
sourcing it from Settings, now fixed.
"""

from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    DEV = "dev"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    SERVICE_NAME: str = "job-service"
    SERVICE_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.LOCAL

    BUILD: str = ""
    GIT_SHA: str = ""

    # Client Service integration (Phase 1) -- internal REST over k8s
    # DNS, per 01-domain-foundations.md §9.
    CLIENT_SERVICE_BASE_URL: str = "http://client-service:8000"
    CLIENT_SERVICE_TIMEOUT_SECONDS: float = 2.0

    # JWT verification (consumer only -- job-service issues no
    # tokens). Platform Conventions §7. Values ported from
    # client-service's own Settings -- the same identity-service
    # issues tokens for every consumer.
    JWKS_URL: str = "http://localhost:8001/.well-known/jwks.json"
    JWKS_ISSUER: str = "https://identity.flowtona.dev"
    JWKS_AUDIENCE: str = "flowtona-api"
    JWKS_ALGORITHM: str = "ES256"
    JWKS_CACHE_TTL_SECONDS: int = 3600
    JWKS_FETCH_TIMEOUT_SECONDS: int = 5

    # RFC 9457 Problem Details -- base URI for error `type` fields.
    # Same value and validation logic as client-service's own
    # ERROR_BASE_URI (a shared platform convention, not service-
    # specific) -- ported exactly, ValueError messages included.
    ERROR_BASE_URI: str = "https://flowtona.dev/errors"

    @field_validator("ERROR_BASE_URI")
    @classmethod
    def _validate_error_base_uri(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("ERROR_BASE_URI must not contain surrounding whitespace")

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(
                f"ERROR_BASE_URI must use the http or https scheme, got: {value!r}"
            )
        if not parsed.netloc:
            raise ValueError(f"ERROR_BASE_URI must include a host, got: {value!r}")
        if parsed.username or parsed.password:
            raise ValueError("ERROR_BASE_URI must not contain user credentials.")
        if not parsed.path or parsed.path == "/":
            raise ValueError(
                f"ERROR_BASE_URI must include a non-root path (e.g. /errors), got: {value!r}"
            )
        if value.endswith("/"):
            raise ValueError(
                f"ERROR_BASE_URI must not have a trailing slash, got: {value!r}"
            )
        if parsed.query or parsed.fragment:
            raise ValueError(
                "ERROR_BASE_URI must not contain a query string or fragment, "
                f"got: {value!r}"
            )
        return value
