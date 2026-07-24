"""
app/api/system_meta.py

Service metadata endpoints — informational, not health checks.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_token_service
from app.core.config import Settings
from app.services.token_service import TokenService

router = APIRouter(tags=["system"])


@router.get("/info")
async def info(request: Request) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    return {
        "service_name": settings.SERVICE_NAME,
        "service_version": settings.SERVICE_VERSION,
        "environment": settings.ENVIRONMENT.value,
    }


@router.get("/.well-known/jwks.json")
async def jwks(
    token_service: TokenService = Depends(get_token_service),
) -> dict[str, Any]:
    return await token_service.build_jwks()
