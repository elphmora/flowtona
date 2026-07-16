"""
app/services/permission_service.py

Owns real authorization policy — role-to-permission resolution,
email-verification soft gating, and the effect of inactive/suspended/
revoked memberships on effective permissions. Not a thin wrapper over
constants/permissions.py's static mapping (see the ADR's Entity &
Convention Clarifications on why this needed to be a service, not a
dict lookup).

Deliberately synchronous, pure logic — no repository calls. Callers
(AuthService, route dependencies) already have the User and
TenantMembership in hand; this service just answers "what can this
person do, right now, in this tenant."
"""

from app.constants.permissions import (
    SOFT_GATED_PERMISSIONS,
    Permission,
    permissions_for_role,
)
from app.models.membership import MembershipStatus, TenantMembership
from app.models.user import User


class PermissionService:
    def effective_permissions(
        self,
        *,
        user: User,
        membership: TenantMembership,
    ) -> frozenset[Permission]:
        if membership.user_id != user.id:
            raise ValueError(
                "membership.user_id does not match user.id — refusing to "
                "compute permissions for a mismatched pair"
            )

        if membership.status != MembershipStatus.ACTIVE:
            return frozenset()

        base = permissions_for_role(membership.role)

        if not user.email_verified:
            return base - SOFT_GATED_PERMISSIONS

        return base

    def has_permission(
        self,
        *,
        user: User,
        membership: TenantMembership,
        permission: Permission,
    ) -> bool:
        return permission in self.effective_permissions(
            user=user, membership=membership
        )
