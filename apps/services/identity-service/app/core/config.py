"""
Identity Service configuration.

Loads all settings from environment variables with sensible local defaults.
"""

from enum import StrEnum

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
    SERVICE_NAME: str = "identity-service"
    SERVICE_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.LOCAL

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # JWT access tokens — ES256 + JWKS, Decision 4
    JWT_ALGORITHM: str = "ES256"
    JWT_ISSUER: str = "https://identity.flowtona.dev"
    JWT_AUDIENCE: str = "flowtona-api"
    JWT_SIGNING_KEY_ID: str = "flowtona-local-001"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15

    # Opaque refresh token — provisional Phase 1 lifetime
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Tenant-selection pre-auth token
    PREAUTH_TOKEN_EXPIRE_SECONDS: int = 120

    # CORS policy deferred; no origins enabled by default
    CORS_ORIGINS: list[str] = []

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # OpenTelemetry — tracing deferred and disabled by default
    OTEL_EXPORTER_ENDPOINT: str = ""
    OTEL_ENABLED: bool = False

    # Metrics
    METRICS_ENABLED: bool = True

    # Source-based authentication rate limiting
    AUTH_SOURCE_RATE_LIMIT_REQUESTS: int = 10
    AUTH_SOURCE_RATE_LIMIT_WINDOW_SECONDS: int = 60

    # Progressive per-account throttling
    AUTH_ACCOUNT_DELAY_START_AFTER_FAILURES: int = 3
    AUTH_ACCOUNT_DELAY_MAX_SECONDS: int = 30
    AUTH_ACCOUNT_FAILURE_DECAY_SECONDS: int = 1800


settings = Settings()
