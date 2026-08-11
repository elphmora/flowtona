"""
app/core/config.py

client-service configuration. Same shape as identity-service's
Settings (BaseSettings, .env support), diverging where client-service's
actual needs differ: no signing key material (it issues no tokens), no
password hashing, no session-lifetime settings — instead, JWKS-consumer
settings (Platform Conventions §7) identity-service, as an issuer
rather than a consumer, has no equivalent of.
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

    # Service identity
    SERVICE_NAME: str = "client-service"
    SERVICE_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.LOCAL

    # Injected by CI/CD during build. Defaults are only for local
    # development.
    BUILD_ID: str = "unknown"
    GIT_SHA: str = "unknown"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # JWT verification (consumer only — client-service issues no
    # tokens). Decision 1 / Platform Conventions §7.
    #
    # JWKS_URL is the network location JWKS is FETCHED from — internal
    # k8s DNS per Decision 1, never Kong for east-west calls. The
    # LOCAL default assumes identity-service running on a different
    # local port than client-service's own; override per environment —
    # the real non-local value is a k8s Service DNS name, not this
    # placeholder.
    JWKS_URL: str = "http://localhost:8001/.well-known/jwks.json"

    # JWKS_ISSUER / JWKS_AUDIENCE / JWKS_ALGORITHM are the EXPECTED
    # claim values a verified token must carry — distinct from
    # JWKS_URL, which is only where to fetch keys from. Both confirmed
    # against identity-service's actual Settings/TokenService
    # implementation (feature/identity-service-access-token-
    # permissions, merged into develop and confirmed via a real
    # signup/login smoke test against a running identity-service
    # instance) — not guessed, and no longer flagged as unconfirmed.
    JWKS_ISSUER: str = "https://identity.flowtona.dev"
    JWKS_AUDIENCE: str = "flowtona-api"

    JWKS_ALGORITHM: str = "ES256"

    # Fallback cache TTL when the JWKS response doesn't include its own
    # Cache-Control/ETag headers to honor (Platform Conventions §7:
    # caching follows standard JWKS caching headers — this is only the
    # floor behavior, not the primary mechanism).
    JWKS_CACHE_TTL_SECONDS: int = 3600
    JWKS_FETCH_TIMEOUT_SECONDS: int = 5

    # CORS policy deferred; no origins enabled by default (Platform
    # Conventions §12).
    CORS_ORIGINS: list[str] = []

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # OpenTelemetry — deferred and disabled by default (Platform
    # Conventions §12) — client-service's own traffic is what first
    # makes this a genuine need, per platform-conventions.md.
    OTEL_EXPORTER_ENDPOINT: str = ""
    OTEL_ENABLED: bool = False

    # Metrics
    METRICS_ENABLED: bool = True

    # RFC 9457 Problem Details — base URI for error `type` fields.
    # Same value and validation logic as identity-service's
    # ERROR_BASE_URI (Platform Conventions §6) — a shared platform
    # convention, not service-specific, so this stays identical rather
    # than diverging for no reason.
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


settings = Settings()
