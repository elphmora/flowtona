"""
app/api/v1/router.py

Assembles all v1 API routes into one router, included once in
main.py. Routes are added here as their respective PRs land — auth
(signup/login/select-tenant) is the first.
"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router

router = APIRouter(prefix="/v1")
router.include_router(auth_router)
