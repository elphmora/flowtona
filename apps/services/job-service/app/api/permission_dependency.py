"""
app/api/permission_dependency.py

FastAPI dependency factory for permission-gated job-service routes.

Authentication is performed first by get_current_claims(); this
dependency then checks the verified token's permissions claim for the
exact permission required. It does not interpret roles or reconstruct
identity-service's authorization policy -- it has no knowledge of how
a permission was derived, only whether the verified token carries it.

require_permission(permission: RequiredPermission) -- typed as a
Union (app/constants/permissions.py: JobPermission |
Literal["clients:read"]), not plain str. An earlier version of this
file used plain str -- needed because Create Job pre-checks BOTH
jobs:write (job-service's own permission) AND clients:read (Client
Service's foreign permission, forwarded per Amendment 7) through the
same factory -- but str gave up ALL static type-checking at every call
site, not just the one case that actually needed loosening.
RequiredPermission is narrower than a job-service-owns-everything
Literal and wider than client-service's own single-namespace one --
shaped to exactly what this service needs to check, nothing more.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends

from app.api.auth_dependency import get_current_claims
from app.constants.permissions import RequiredPermission
from app.exceptions.auth import InsufficientPermissionError
from app.metrics.business_metrics import PERMISSION_DENIED_TOTAL
from app.security.token_verifier import AccessTokenClaims

AuthenticatedClaims = Annotated[
    AccessTokenClaims,
    Depends(get_current_claims),
]


def require_permission(
    permission: RequiredPermission,
) -> Callable[..., Coroutine[Any, Any, AccessTokenClaims]]:
    async def _check(claims: AuthenticatedClaims) -> AccessTokenClaims:
        if permission not in claims.permissions:
            PERMISSION_DENIED_TOTAL.labels(permission=permission).inc()
            raise InsufficientPermissionError()
        return claims

    return _check
