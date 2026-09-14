"""
app/api/system/info.py

GET /info per Platform Conventions §9. Reads Settings from
request.app.state.settings — the exact instance create_app() resolved
and stored during lifespan — never constructs its own Settings().

Uses the Annotated[Type, Depends(...)] dependency-injection style
rather than `settings: Settings = Depends(get_settings)` — the latter
trips ruff's B008 (flake8-bugbear's "no function calls in argument
defaults" rule), which doesn't special-case FastAPI's own Depends()
idiom. Annotated moves the Depends() call into type-annotation
metadata rather than a literal default value, which is both the
current FastAPI-recommended style and avoids the false positive
without needing a project-wide lint suppression.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings

router = APIRouter(tags=["system"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/info")
async def info(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.SERVICE_VERSION,
        "build": settings.BUILD,
        "git_sha": settings.GIT_SHA,
        "environment": settings.ENVIRONMENT.value,
    }
