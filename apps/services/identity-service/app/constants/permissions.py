"""
app/constants/permissions.py

Permission set and the fixed role->permission mapping, per Decision 5
(fixed roles + permission sets in code, central mapping — not tenant-
customizable in Phase 1). This is the single source of truth services
check against; there is no persisted permission data.

Naming convention: namespaced "resource:action" (e.g. "members:invite"),
not "can_*" — chosen because it scales cleanly across services (scheduling-
service's "schedule:read" and identity-service's "schedule:read"-adjacent
concerns won't collide or need disambiguating prefixes the way a flat
can_* namespace would). This replaces the can_* names used in earlier
drafts of the API contract; 01-api-contract.md has been updated to match.
"""

from enum import StrEnum

from app.constants.roles import Role


class Permission(StrEnum):
    BILLING_MANAGE = "billing:manage"
    SCHEDULE_READ = "schedule:read"
    MEMBERS_INVITE = "members:invite"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(
        {
            Permission.BILLING_MANAGE,
            Permission.SCHEDULE_READ,
            Permission.MEMBERS_INVITE,
        }
    ),
    Role.DISPATCHER: frozenset(
        {
            Permission.SCHEDULE_READ,
            Permission.MEMBERS_INVITE,
        }
    ),
    Role.TECHNICIAN: frozenset(
        {
            Permission.SCHEDULE_READ,
        }
    ),
}


def permissions_for_role(role: Role) -> frozenset[Permission]:
    """Pure lookup against the static mapping above. Real authorization
    policy (soft-gating on email_verified, membership status handling)
    lives in services/permission_service.py, not here — this function is
    intentionally dumb."""
    return ROLE_PERMISSIONS[role]


# Decision 18's soft gate, made explicit rather than inferred inside
# PermissionService. Decision 18's own text names "inviting teammates"
# and "anything billing-related" as gated behind email confirmation —
# that maps directly to these two permissions. SCHEDULE_READ (viewing
# your own schedule) is basic functionality, not team/billing
# management, so it's deliberately NOT in this set — it stays available
# regardless of verification status.
SOFT_GATED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.BILLING_MANAGE,
        Permission.MEMBERS_INVITE,
    }
)
