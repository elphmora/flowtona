"""
app/services/auth_service.py

The primary orchestration layer for authentication workflows,
composing multiple domain services into complete authentication use
cases (signup, login, refresh, invite acceptance, etc.). Owns almost
no business rules of its own; every method delegates to the entity
service that actually owns the relevant rule (PermissionService for
authorization checks, MembershipService for membership state, and so
on). This mirrors the layering already established throughout this
codebase: repositories own persistence and atomic state transitions,
entity services own aggregate-specific business rules, AuthService
owns workflows spanning more than one of them.

This file is the skeleton only — constructor wiring and method
signatures, with method bodies deferred to focused follow-up PRs
(signup/login/tenant-selection; refresh/logout/logout-all; email
verification; invitations), given how much review churn every
individual service in this build has gone through — a single PR
covering all ten methods at once would be unreviewable.

KNOWN GAPS, not solved anywhere in this codebase yet:
- Rate limiting (Decision 12) is intentionally handled outside this
  business layer — a different layer's concern (HTTP middleware), not
  business logic; no RateLimitService exists.
- signup() and accept_invite_new_user() span multiple repositories
  without a transaction (User + Tenant + Membership + EmailVerification,
  or User + Membership + mark_accepted) — already tracked in the ADR's
  Deferred Decisions: Unit of Work entry. AuthService must not imply
  atomicity the repositories can't provide.

Future work (deliberately not addressed now, recorded here so a
future reader doesn't wonder whether it was simply forgotten):
- transactional orchestration / Unit of Work for the multi-repository
  workflows noted above
- authentication metrics (Decision 17 already commits to Prometheus
  counters generally; wiring specific ones is scheduled for after
  containerization/deployment, not this branch)
- audit event publication — no consumer (SIEM, audit log, analytics
  pipeline) exists yet to justify building it ahead of that need
"""

from uuid import UUID

from app.constants.roles import Role
from app.models.invitation import Invitation
from app.services.auth_email_sender import AuthEmailSender
from app.services.auth_models import (
    AuthenticatedSession,
    InviteAcceptanceResult,
    TenantSelectionRequired,
)
from app.services.email_verification_service import EmailVerificationService
from app.services.invitation_service import InvitationService
from app.services.membership_service import MembershipService
from app.services.permission_service import PermissionService
from app.services.refresh_token_service import RefreshTokenService
from app.services.tenant_service import TenantService
from app.services.token_service import TokenService
from app.services.user_service import UserService


class AuthService:
    def __init__(
        self,
        *,
        user_service: UserService,
        tenant_service: TenantService,
        membership_service: MembershipService,
        email_verification_service: EmailVerificationService,
        invitation_service: InvitationService,
        refresh_token_service: RefreshTokenService,
        token_service: TokenService,
        permission_service: PermissionService,
        email_sender: AuthEmailSender,
    ) -> None:
        self._user_service = user_service
        self._tenant_service = tenant_service
        self._membership_service = membership_service
        self._email_verification_service = email_verification_service
        self._invitation_service = invitation_service
        self._refresh_token_service = refresh_token_service
        self._token_service = token_service
        self._permission_service = permission_service
        self._email_sender = email_sender

    async def signup(
        self, *, email: str, password: str, display_name: str, tenant_label: str
    ) -> AuthenticatedSession:
        """Flow 1. UserService.create -> TenantService.create ->
        MembershipService.create(role=owner) -> RefreshTokenService.issue
        -> TokenService.issue_access_token -> EmailVerificationService.create
        -> email_sender.send_verification_email (failure caught, not
        propagated — Decision 18's soft gate)."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def login(
        self, *, email: str, password: str
    ) -> AuthenticatedSession | TenantSelectionRequired:
        """Flows 2/3. UserService.get_by_email -> verify_password ->
        MembershipService.get_memberships_for_user, filtered to ACTIVE
        status only -> branch on count:
            0 -> NoActiveMembershipError
            1 -> AuthenticatedSession
            2+ -> TenantSelectionRequired
        Wrong email and wrong password both raise InvalidCredentialsError
        identically, to avoid user enumeration."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def select_tenant(
        self, *, preauth_token: str, tenant_id: UUID
    ) -> AuthenticatedSession:
        """Flow 3 continuation. Verifies the preauth token, then does a
        FRESH MembershipService lookup for the chosen tenant_id — never
        trusts anything embedded in the preauth token itself (matches
        PreauthTokenClaims' deliberately minimal design)."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def refresh(self, *, raw_refresh_token: str) -> AuthenticatedSession:
        """Flow 4. RefreshTokenService.rotate() first — the only way to
        learn user_id/tenant_id from an opaque refresh token (Decision
        3) without a repository lookup, and rotate()'s own atomic guard
        is the real race-safety mechanism regardless of ordering. Then
        a FRESH MembershipService lookup — role/permissions_version
        live on TenantMembership, not RefreshTokenRecord, so refresh
        must reflect current permissions, not whatever was true at
        original login.

        If the membership is inactive after rotation, the refresh-token
        family is revoked before the operation fails — no valid session
        survives a revoked membership."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def logout(self, *, raw_refresh_token: str) -> None:
        """Flow 9. Thin delegation to
        RefreshTokenService.revoke_current_session()."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def logout_all_for_tenant(self, *, user_id: UUID, tenant_id: UUID) -> int:
        """Flow 10. Revokes every session for this user WITHIN this
        tenant only — not a genuine logout-everywhere. user_id/tenant_id
        come from the caller's own verified access token (route/
        middleware layer), never raw client input. Thin delegation to
        RefreshTokenService.revoke_all_for_tenant()."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def verify_email(self, *, raw_token: str) -> None:
        """Flow 1 continuation. EmailVerificationService.verify()
        (consume-first, atomic) -> UserService.mark_email_verified() ->
        MembershipService.bump_permissions_version_for_user()."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def resend_verification_email(self, *, user_id: UUID) -> None:
        """user_id from an authenticated caller — the soft gate means
        they're already logged in and simply haven't verified yet, so
        this doesn't accept a bare email address. UserService.get_by_id
        for the address -> EmailVerificationService.resend() ->
        email_sender.send_verification_email."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def create_invite(
        self, *, tenant_id: UUID, email: str, role: Role, invited_by_user_id: UUID
    ) -> Invitation:
        """Flow 6. PermissionService check (members:invite) ->
        duplicate-membership guard -> InvitationService.create() ->
        email_sender.send_invitation_email."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def accept_invite_existing_user(
        self, *, raw_token: str, authenticated_user_id: UUID
    ) -> InviteAcceptanceResult:
        """Flow 7. InvitationService.resolve_pending() -> compare
        invite.email against the authenticated user's email
        (InvitationEmailMismatchError on mismatch — this comparison can
        only happen here, since InvitationService deliberately has no
        User access) -> MembershipService.create() ->
        InvitationService.mark_accepted() LAST, not first (acceptance
        spans multiple aggregates — see InvitationService's own
        docstring on why marking accepted first would risk a
        permanently-burned invite if membership creation then failed).
        Does NOT mint a new session — see InviteAcceptanceResult's
        docstring."""
        raise NotImplementedError("Implemented in a follow-up PR")

    async def accept_invite_new_user(
        self, *, raw_token: str, password: str, display_name: str
    ) -> AuthenticatedSession:
        """Flow 8. Same shape as accept_invite_existing_user(), but
        UserService.create(..., email_verified=True) — Invariant 9:
        accepting a mailed invite link IS proof of mailbox ownership.
        Unlike the existing-user case, there's no prior session to
        avoid duplicating, so this DOES return a full
        AuthenticatedSession — the user's very first one."""
        raise NotImplementedError("Implemented in a follow-up PR")
