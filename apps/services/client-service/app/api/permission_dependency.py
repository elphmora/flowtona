"""
app/api/permission_dependency.py

FastAPI dependency factory for permission-gated client-service routes.

Authentication is performed first by get_current_claims(); this
dependency then checks the verified token's permissions claim for the
exact permission required by the route. It does not interpret roles
or reconstruct identity-service's authorization policy — it has no
knowledge of how a permission was derived, only whether the verified
token carries it (Platform Conventions §13: client-service authorizes
exclusively from `permissions`).

Uses typing.Annotated for the inner dependency (AuthenticatedClaims),
matching auth_dependency.py's own convention — see that module's
docstring for why.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends

from app.api.auth_dependency import get_current_claims
from app.constants.permissions import ClientPermission
from app.exceptions.auth import InsufficientPermissionError
from app.security.token_verifier import AccessTokenClaims

AuthenticatedClaims = Annotated[
    AccessTokenClaims,
    Depends(get_current_claims),
]


def require_permission(
    permission: ClientPermission,
) -> Callable[..., Coroutine[Any, Any, AccessTokenClaims]]:
    async def _check(claims: AuthenticatedClaims) -> AccessTokenClaims:
        if permission not in claims.permissions:
            raise InsufficientPermissionError()
        return claims

    return _check
