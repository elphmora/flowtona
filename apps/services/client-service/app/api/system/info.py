"""
app/api/system/info.py

GET /info — service identity/build metadata (Platform Conventions
§9). No GET /.well-known/jwks.json here — that endpoint is published
only by services that ISSUE JWTs (identity-service currently);
client-service is a JWKS CONSUMER, not an issuer, and has nothing of
its own to publish there.
"""

from fastapi import APIRouter

from app.core.config import settings as default_settings

router = APIRouter(tags=["system"])


@router.get("/info")
async def info() -> dict[str, str]:
    return {
        "service": default_settings.SERVICE_NAME,
        "version": default_settings.SERVICE_VERSION,
        "build": default_settings.BUILD_ID,
        "git_sha": default_settings.GIT_SHA,
        "environment": default_settings.ENVIRONMENT.value,
    }
