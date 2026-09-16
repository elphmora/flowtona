"""
app/core/config.py

job-service configuration.
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

    BUILD: str = ""
    GIT_SHA: str = ""

    # Client Service integration (Phase 1) -- internal REST over k8s
    # DNS, per 01-domain-foundations.md §9. Timeout is DD-009's
    # explicit placeholder (not derived from measured latency yet) --
    # kept as a setting, not hardcoded, since DD-009 frames it as
    # something that will need tuning later without a code change.
    CLIENT_SERVICE_BASE_URL: str = "http://client-service:8000"
    CLIENT_SERVICE_TIMEOUT_SECONDS: float = 2.0
