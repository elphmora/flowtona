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

CLIENTS_READ/CLIENTS_WRITE added implementing client-service-
architecture.md Decision 3 (owner/dispatcher: both; technician:
CLIENTS_READ only) — this is the ONE place that mapping is allowed to
live, per the whole cross-service architecture: permissions are
resolved centrally here and embedded in the access token, never
re-derived from `role` by a consuming service. Deliberately NOT added
to SOFT_GATED_PERMISSIONS — client-service's own ADR treats client
management as core day-1 functionality for a field-service business,
the same category SCHEDULE_READ is already in below, not an
administrative/billing action worth gating behind email verification.

JOBS_READ/JOBS_WRITE added implementing job-service's own Create Job
authorization contract (03-api-contract.md: POST /v1/jobs requires
jobs:write). Mirrors CLIENTS_READ/CLIENTS_WRITE's exact role pattern —
owner/dispatcher: both; technician: JOBS_READ only, never JOBS_WRITE (a
technician can see jobs but not create them — only dispatchers/owners
raise new work). Same reasoning, same category as CLIENTS_*: job
creation is core field-service functionality, not an administrative/
billing action, so also deliberately NOT added to SOFT_GATED_PERMISSIONS.

This was the ONE file that needed changing to close the gap discovered
when job-service's real POST /v1/jobs was first exercised against a
real identity-service-issued token — PermissionService, TokenService,
and AuthService are all generic over this enum/dict (confirmed by
reading their real source), so no other file requires modification.
Every token-issuing path (signup, login, refresh, select_tenant — all
routing through AuthService's shared call to PermissionService.
effective_permissions()) picks up the fix uniformly and automatically,
not duplicated per-flow.
"""

from enum import StrEnum

from app.constants.roles import Role


class Permission(StrEnum):
    BILLING_MANAGE = "billing:manage"
    SCHEDULE_READ = "schedule:read"
    MEMBERS_INVITE = "members:invite"
    CLIENTS_READ = "clients:read"
    CLIENTS_WRITE = "clients:write"
    JOBS_READ = "jobs:read"
    JOBS_WRITE = "jobs:write"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(
        {
            Permission.BILLING_MANAGE,
            Permission.SCHEDULE_READ,
            Permission.MEMBERS_INVITE,
            Permission.CLIENTS_READ,
            Permission.CLIENTS_WRITE,
            Permission.JOBS_READ,
            Permission.JOBS_WRITE,
        }
    ),
    Role.DISPATCHER: frozenset(
        {
            Permission.SCHEDULE_READ,
            Permission.MEMBERS_INVITE,
            Permission.CLIENTS_READ,
            Permission.CLIENTS_WRITE,
            Permission.JOBS_READ,
            Permission.JOBS_WRITE,
        }
    ),
    Role.TECHNICIAN: frozenset(
        {
            Permission.SCHEDULE_READ,
            Permission.CLIENTS_READ,
            Permission.JOBS_READ,
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
# your own schedule), CLIENTS_READ/CLIENTS_WRITE, and JOBS_READ/
# JOBS_WRITE (client-service Decision 3 / job-service's own contract —
# core field-service business functionality, not team/billing
# management) are deliberately NOT in this set — they stay available
# regardless of verification status.
SOFT_GATED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.BILLING_MANAGE,
        Permission.MEMBERS_INVITE,
    }
)
