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

PR scope: signup(), login(), select_tenant() only. The remaining seven
methods stay NotImplementedError stubs, filled in across the follow-up
PRs already agreed (refresh/logout/logout-all; email verification;
invitations) — a single PR covering all ten methods at once would be
unreviewable, given how much review churn every individual service in
this build has gone through.

KNOWN GAPS, not solved anywhere in this codebase yet:
- Rate limiting (Decision 12) is intentionally handled outside this
  business layer — a different layer's concern (HTTP middleware), not
  business logic; no RateLimitService exists.
- signup() spans multiple repositories without a transaction (User +
  Tenant + Membership + EmailVerification) — already tracked in the
  ADR's Deferred Decisions: Unit of Work entry. AuthService must not
  imply atomicity the repositories can't provide.

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
from app.exceptions.auth import InvalidCredentialsError, NoActiveMembershipError
from app.exceptions.base import IdentityInvariantError
from app.models.invitation import Invitation
from app.models.membership import MembershipStatus, TenantMembership
from app.models.tenant import Tenant
from app.models.user import User
from app.security.hashing import verify_password
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

    async def _issue_session(
        self, *, user: User, tenant: Tenant, membership: TenantMembership
    ) -> AuthenticatedSession:
        """Issues a new refresh-token session and matching access
        token. Used by signup(), login()'s single-active-membership
        path, and select_tenant() — the access token always reflects
        the given membership's CURRENT role/permissions_version, not
        any cached value."""
        _, raw_refresh_token = await self._refresh_token_service.issue(
            user_id=user.id, tenant_id=tenant.id
        )
        access_token = await self._token_service.issue_access_token(
            user_id=user.id,
            tenant_id=tenant.id,
            role=membership.role,
            permissions_version=membership.permissions_version,
        )
        return AuthenticatedSession(
            user=user,
            tenant=tenant,
            membership=membership,
            access_token=access_token,
            raw_refresh_token=raw_refresh_token,
        )

    async def signup(
        self, *, email: str, password: str, display_name: str, tenant_label: str
    ) -> AuthenticatedSession:
        """Flow 1. Only email-delivery failure is caught and suppressed
        (Decision 18's soft gate — the account is already fully usable,
        a failed send is recoverable via resend, not a signup failure).
        Failure to create the verification RECORD itself is NOT
        suppressed — that's an internal workflow failure, not an
        unreliable external delivery channel, and should propagate
        like any other signup step failing."""
        user = await self._user_service.create(
            email=email, password=password, display_name=display_name
        )
        tenant = await self._tenant_service.create(tenant_label=tenant_label)
        membership = await self._membership_service.create(
            user_id=user.id, tenant_id=tenant.id, role=Role.OWNER
        )

        session = await self._issue_session(
            user=user, tenant=tenant, membership=membership
        )

        raw_verification_token = await self._email_verification_service.create(
            user_id=user.id, email=user.email
        )
        try:
            await self._email_sender.send_verification_email(
                to=user.email, raw_token=raw_verification_token
            )
        except Exception as exc:
            # Deliberately broad — isolating an inherently unreliable
            # external dependency (email delivery) is exactly the
            # legitimate case for catching Exception broadly. Any
            # failure here must never fail signup itself (Decision 18).
            # TODO: log email delivery failure (Decision 17) once
            # structured logging is wired up.
            del exc

        return session

    async def login(
        self, *, email: str, password: str
    ) -> AuthenticatedSession | TenantSelectionRequired:
        """Flows 2/3. Missing user and wrong password raise the exact
        same InvalidCredentialsError — same message, code, and status —
        to avoid user enumeration via the login endpoint's response."""
        user = await self._user_service.get_by_email(email=email)
        if user is None:
            raise InvalidCredentialsError()
        if not verify_password(password=password, password_hash=user.password_hash):
            raise InvalidCredentialsError()

        memberships = await self._membership_service.get_memberships_for_user(
            user_id=user.id
        )
        active_memberships = [
            m for m in memberships if m.status == MembershipStatus.ACTIVE
        ]

        if len(active_memberships) == 0:
            raise NoActiveMembershipError()

        if len(active_memberships) == 1:
            membership = active_memberships[0]
            tenant = await self._tenant_service.get_by_id(
                tenant_id=membership.tenant_id
            )
            if tenant is None:
                raise IdentityInvariantError(
                    f"Membership {membership.id} references missing "
                    f"tenant {membership.tenant_id}"
                )
            return await self._issue_session(
                user=user, tenant=tenant, membership=membership
            )

        preauth_token = await self._token_service.issue_preauth_token(user_id=user.id)
        return TenantSelectionRequired(user=user, preauth_token=preauth_token)

    async def select_tenant(
        self, *, preauth_token: str, tenant_id: UUID
    ) -> AuthenticatedSession:
        """Flow 3 continuation. Verifies the preauth token, then does a
        FRESH MembershipService lookup for the CLIENT-SUPPLIED tenant_id
        — never trusts anything embedded in the preauth token itself
        (Invariant 14: a pre-auth token identifies a user, never a
        tenant). Reuses NoActiveMembershipError when the requested
        membership is missing or inactive — same semantic outcome as
        login()'s zero-membership case ("valid identity, no active
        authorization path for this tenant"), just discovered at a
        different step; not worth a separate exception whose only
        distinction would be which step found it. Uses the SAME session-
        issuance tail as signup() — NOT the rest of signup's workflow;
        this does not create another email-verification token or
        resend a verification email."""
        claims = await self._token_service.verify_preauth_token(token=preauth_token)

        membership = await self._membership_service.get_by_user_and_tenant(
            user_id=claims.user_id, tenant_id=tenant_id
        )
        if membership is None or membership.status != MembershipStatus.ACTIVE:
            raise NoActiveMembershipError()

        user = await self._user_service.get_by_id(user_id=claims.user_id)
        if user is None:
            raise IdentityInvariantError(
                f"Preauth token references missing user {claims.user_id}"
            )
        tenant = await self._tenant_service.get_by_id(tenant_id=tenant_id)
        if tenant is None:
            raise IdentityInvariantError(
                f"Membership {membership.id} references missing tenant {tenant_id}"
            )

        return await self._issue_session(
            user=user, tenant=tenant, membership=membership
        )

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
