"""
app/api/v1/router.py

Assembles all v1 API routes into one router, included once in
main.py. auth.py covers authentication (signup, login, sessions,
verification); invites.py covers organisation-membership onboarding —
related but distinct API areas, given their own routers rather than
one growing file.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.invites import router as invites_router

router = APIRouter(prefix="/v1")
router.include_router(auth_router)
router.include_router(invites_router)
