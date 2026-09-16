"""
tests/unit/api/test_permission_dependency.py
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.permission_dependency import require_permission
from app.constants.permissions import CLIENTS_READ, JOBS_WRITE
from app.exceptions.auth import InsufficientPermissionError
from app.security.token_verifier import AccessTokenClaims


def _make_claims(permissions: frozenset[str]) -> AccessTokenClaims:
    return AccessTokenClaims(
        sub=uuid4(),
        tenant_id=uuid4(),
        role="dispatcher",
        permissions=permissions,
        permissions_version=1,
        token_type="access",
        jti=uuid4(),
    )


async def test_require_permission_raises_when_permission_missing() -> None:
    check = require_permission(JOBS_WRITE)
    claims = _make_claims(frozenset({"jobs:read"}))

    with pytest.raises(InsufficientPermissionError):
        await check(claims)


async def test_require_permission_returns_claims_when_permission_present() -> None:
    check = require_permission(JOBS_WRITE)
    claims = _make_claims(frozenset({"jobs:write"}))

    result = await check(claims)

    assert result is claims


async def test_require_permission_works_for_clients_read() -> None:
    """Proves the same factory serves job-service's own permission
    namespace AND Client Service's foreign one -- the reason
    require_permission() is typed `permission: str`, not the narrower
    JobPermission literal."""
    check = require_permission(CLIENTS_READ)
    claims = _make_claims(frozenset({"clients:read"}))

    result = await check(claims)

    assert result is claims
