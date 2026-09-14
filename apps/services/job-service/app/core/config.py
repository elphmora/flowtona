"""
app/core/config.py

job-service configuration. No signing key material (issues no tokens),
no JWKS-consumer settings yet — those land in Phase 1 alongside the
first protected route (see app/main.py's docstring history for why
TokenVerifier itself is deferred).
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

    SERVICE_NAME: str = "job-service"
    SERVICE_VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = Environment.LOCAL

    # Injected by CI/CD during build. Defaults are only for local
    # development, where no build pipeline exists yet.
    BUILD: str = ""
    GIT_SHA: str = ""
