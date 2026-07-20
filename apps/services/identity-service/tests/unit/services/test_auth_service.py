"""tests/unit/services/test_auth_service.py

Unit tests for AuthService's authentication workflows.

Covers all ten public methods: signup(), login(), select_tenant(),
refresh(), logout(), logout_all_for_tenant(), verify_email(),
resend_verification_email(), create_invite(),
accept_invite_existing_user(), accept_invite_new_user(), plus
constructor/DI wiring. Built incrementally across five PRs matching
AuthService's own build order.
"""

from uuid import uuid4

import pytest

from app.constants.roles import Role
from app.exceptions.auth import (
    InvalidCredentialsError,
    NoActiveMembershipError,
    PermissionDeniedError,
)
from app.exceptions.base import IdentityInvariantError
from app.exceptions.email_verification import VerificationTokenInvalidError
from app.exceptions.invitation import (
    InvitationEmailMismatchError,
    InvitationInvalidError,
)
from app.exceptions.membership import AlreadyAMemberError
from app.exceptions.refresh_token import (
    InvalidRefreshTokenError,
    RefreshTokenReuseDetectedError,
)
from app.exceptions.token import InvalidPreauthTokenError
from app.exceptions.user import EmailAlreadyRegisteredError
from app.models.tenant import Tenant
from app.models.user import User
from app.security.secret_provider import FileSecretProvider
from app.services.auth_email_sender import AuthEmailSender
from app.services.auth_models import AuthenticatedSession, TenantSelectionRequired
from app.services.auth_service import AuthService
from app.services.email_verification_service import EmailVerificationService
from app.services.invitation_service import InvitationService
from app.services.membership_service import MembershipService
from app.services.permission_service import PermissionService
from app.services.refresh_token_service import RefreshTokenService
from app.services.tenant_service import TenantService
from app.services.token_service import TokenService
from app.services.user_service import UserService
from scripts.generate_signing_keypair import generate_keypair


class _NoopEmailSender:
    """Stand-in AuthEmailSender for tests — no real implementation
    exists yet (see auth_email_sender.py's module docstring). Tracks
    what was "sent" so tests can assert on it without a real email
    backend, including the raw token itself (needed to actually call
    verify_email() with something real in later tests)."""

    def __init__(self) -> None:
        self.verification_emails_sent: list[str] = []
        self.invitation_emails_sent: list[str] = []
        self.last_verification_token_by_email: dict[str, str] = {}

    async def send_verification_email(self, *, to: str, raw_token: str) -> None:
        self.verification_emails_sent.append(to)
        self.last_verification_token_by_email[to] = raw_token

    async def send_invitation_email(
        self, *, to: str, raw_token: str, tenant: Tenant, invited_by: User
    ) -> None:
        self.invitation_emails_sent.append(to)


@pytest.fixture
def email_sender() -> AuthEmailSender:
    return _NoopEmailSender()


@pytest.fixture
def all_services(
    user_repo,
    tenant_repo,
    membership_repo,
    email_verification_repo,
    invitation_repo,
    refresh_token_repo,
    tmp_path,
):
    generate_keypair(tmp_path)
    secret_provider = FileSecretProvider(secrets_dir=tmp_path)

    return {
        "user_service": UserService(user_repo),
        "tenant_service": TenantService(tenant_repo),
        "membership_service": MembershipService(membership_repo),
        "email_verification_service": EmailVerificationService(email_verification_repo),
        "invitation_service": InvitationService(invitation_repo),
        "refresh_token_service": RefreshTokenService(refresh_token_repo),
        "token_service": TokenService(secret_provider),
        "permission_service": PermissionService(),
    }


@pytest.fixture
def auth_service(all_services, email_sender) -> AuthService:
    return AuthService(email_sender=email_sender, **all_services)


class TestSignup:
    pytestmark = pytest.mark.asyncio

    async def test_returns_authenticated_session(self, auth_service):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        assert session.user.email == "dana@example.com"
        assert session.tenant.tenant_label == "Dana's Plumbing"
        assert session.membership.role == Role.OWNER
        assert session.membership.permissions_version == 0
        assert session.access_token
        assert session.raw_refresh_token

    async def test_access_token_verifies_correctly(self, auth_service, all_services):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        claims = await all_services["token_service"].verify_access_token(
            token=session.access_token
        )
        assert claims.user_id == session.user.id
        assert claims.tenant_id == session.tenant.id
        assert claims.role == Role.OWNER

    async def test_sends_verification_email(self, auth_service, email_sender):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        assert session.user.email in email_sender.verification_emails_sent

    async def test_duplicate_email_propagates(self, auth_service):
        await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        with pytest.raises(EmailAlreadyRegisteredError):
            await auth_service.signup(
                email="dana@example.com",
                password="different",
                display_name="Dupe",
                tenant_label="Someone Else's Business",
            )

    async def test_email_delivery_failure_does_not_fail_signup(self, all_services):
        class _FailingEmailSender:
            async def send_verification_email(self, *, to: str, raw_token: str) -> None:
                raise ConnectionError("simulated delivery failure")

            async def send_invitation_email(
                self, *, to: str, raw_token: str, tenant: Tenant, invited_by: User
            ) -> None:
                pass

        service = AuthService(email_sender=_FailingEmailSender(), **all_services)
        session = await service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        assert session.access_token  # signup still succeeded


class TestLogin:
    pytestmark = pytest.mark.asyncio

    async def test_correct_credentials_single_membership_returns_session(
        self, auth_service
    ):
        await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        result = await auth_service.login(email="dana@example.com", password="hunter2")

        assert isinstance(result, AuthenticatedSession)
        assert result.user.email == "dana@example.com"

    async def test_wrong_password_raises_invalid_credentials(self, auth_service):
        await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(email="dana@example.com", password="wrong")

    async def test_unknown_email_raises_same_exception_as_wrong_password(
        self, auth_service
    ):
        """The explicit requirement: missing-user and wrong-password
        must be indistinguishable to the caller — same exception type,
        message, code, and status — to avoid user enumeration."""
        await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        try:
            await auth_service.login(email="dana@example.com", password="wrong")
            wrong_password_exc = None
        except InvalidCredentialsError as exc:
            wrong_password_exc = exc

        try:
            await auth_service.login(
                email="never-signed-up@example.com", password="anything"
            )
            unknown_email_exc = None
        except InvalidCredentialsError as exc:
            unknown_email_exc = exc

        assert wrong_password_exc is not None
        assert unknown_email_exc is not None
        assert type(wrong_password_exc) is type(unknown_email_exc)
        assert wrong_password_exc.code == unknown_email_exc.code
        assert wrong_password_exc.status_code == unknown_email_exc.status_code
        assert wrong_password_exc.detail == unknown_email_exc.detail

    async def test_zero_memberships_raises_no_active_membership(
        self, auth_service, all_services
    ):
        """A user who exists but was never given any membership at
        all — constructed directly via UserService, bypassing
        signup()'s full workflow, since that's the only way to reach
        this state through public APIs."""
        await all_services["user_service"].create(
            email="orphan@example.com", password="hunter2", display_name="Orphan"
        )
        with pytest.raises(NoActiveMembershipError):
            await auth_service.login(email="orphan@example.com", password="hunter2")

    async def test_multiple_memberships_returns_tenant_selection_required(
        self, auth_service, all_services
    ):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        # A second, independent membership for the same user, in a
        # different tenant — simulates having accepted an invite
        # elsewhere (PR 5's job to build the real path for this).
        other_tenant = await all_services["tenant_service"].create(
            tenant_label="Second Business"
        )
        await all_services["membership_service"].create(
            user_id=session.user.id, tenant_id=other_tenant.id, role=Role.TECHNICIAN
        )

        result = await auth_service.login(email="dana@example.com", password="hunter2")

        assert isinstance(result, TenantSelectionRequired)
        assert result.user.id == session.user.id
        claims = await all_services["token_service"].verify_preauth_token(
            token=result.preauth_token
        )
        assert claims.user_id == session.user.id

    async def test_membership_referencing_missing_tenant_raises_invariant_error(
        self, auth_service, all_services
    ):
        """Constructed through the current public service APIs — a
        membership can be made to reference a tenant_id that was never
        actually created."""
        user = await all_services["user_service"].create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        await all_services["membership_service"].create(
            user_id=user.id, tenant_id=uuid4(), role=Role.OWNER
        )
        with pytest.raises(IdentityInvariantError):
            await auth_service.login(email="dana@example.com", password="hunter2")


class TestSelectTenant:
    pytestmark = pytest.mark.asyncio

    async def test_valid_selection_returns_session_for_chosen_tenant(
        self, auth_service, all_services
    ):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        other_tenant = await all_services["tenant_service"].create(
            tenant_label="Second Business"
        )
        await all_services["membership_service"].create(
            user_id=session.user.id, tenant_id=other_tenant.id, role=Role.TECHNICIAN
        )
        login_result = await auth_service.login(
            email="dana@example.com", password="hunter2"
        )
        assert isinstance(login_result, TenantSelectionRequired)

        result = await auth_service.select_tenant(
            preauth_token=login_result.preauth_token, tenant_id=other_tenant.id
        )

        assert isinstance(result, AuthenticatedSession)
        assert result.tenant.id == other_tenant.id
        assert result.membership.role == Role.TECHNICIAN

    async def test_does_not_send_another_verification_email(
        self, auth_service, all_services, email_sender
    ):
        """The explicit requirement: select_tenant() uses only the
        session-issuance tail, not signup's full workflow."""
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        other_tenant = await all_services["tenant_service"].create(
            tenant_label="Second Business"
        )
        await all_services["membership_service"].create(
            user_id=session.user.id, tenant_id=other_tenant.id, role=Role.TECHNICIAN
        )
        login_result = await auth_service.login(
            email="dana@example.com", password="hunter2"
        )
        emails_before = len(email_sender.verification_emails_sent)

        await auth_service.select_tenant(
            preauth_token=login_result.preauth_token, tenant_id=other_tenant.id
        )

        assert len(email_sender.verification_emails_sent) == emails_before

    async def test_nonexistent_membership_raises_no_active_membership(
        self, auth_service, all_services
    ):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        other_tenant = await all_services["tenant_service"].create(
            tenant_label="Second Business"
        )
        await all_services["membership_service"].create(
            user_id=session.user.id, tenant_id=other_tenant.id, role=Role.TECHNICIAN
        )
        login_result = await auth_service.login(
            email="dana@example.com", password="hunter2"
        )

        unrelated_tenant = await all_services["tenant_service"].create(
            tenant_label="Not Dana's"
        )
        with pytest.raises(NoActiveMembershipError):
            await auth_service.select_tenant(
                preauth_token=login_result.preauth_token,
                tenant_id=unrelated_tenant.id,
            )

    async def test_invalid_preauth_token_propagates(self, auth_service):
        with pytest.raises(InvalidPreauthTokenError):
            await auth_service.select_tenant(
                preauth_token="not-a-real-token", tenant_id=uuid4()
            )

    async def test_membership_referencing_missing_user_raises_invariant_error(
        self, auth_service, all_services
    ):
        """A different invariant from the missing-tenant case above —
        here the membership and pre-auth token both reference a user_id
        that was never actually created. Constructed through the
        current public service APIs: TokenService.issue_preauth_token()
        doesn't check the user exists, and neither does
        MembershipService.create()."""
        fake_user_id = uuid4()
        tenant = await all_services["tenant_service"].create(
            tenant_label="Some Business"
        )
        await all_services["membership_service"].create(
            user_id=fake_user_id, tenant_id=tenant.id, role=Role.OWNER
        )
        preauth_token = await all_services["token_service"].issue_preauth_token(
            user_id=fake_user_id
        )

        with pytest.raises(IdentityInvariantError):
            await auth_service.select_tenant(
                preauth_token=preauth_token, tenant_id=tenant.id
            )


class TestRefresh:
    pytestmark = pytest.mark.asyncio

    async def test_returns_new_tokens(self, auth_service):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )

        refreshed = await auth_service.refresh(
            raw_refresh_token=session.raw_refresh_token
        )

        assert refreshed.raw_refresh_token != session.raw_refresh_token
        assert refreshed.access_token != session.access_token
        assert refreshed.user.id == session.user.id
        assert refreshed.tenant.id == session.tenant.id

    async def test_reflects_current_permissions_version(
        self, auth_service, all_services
    ):
        """Refresh must use CURRENT membership state, not whatever was
        true at original login — simulated by bumping
        permissions_version directly (verify_email(), which would do
        this via the real workflow, isn't implemented until PR 4)."""
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        assert session.membership.permissions_version == 0

        await all_services["membership_service"].bump_permissions_version_for_user(
            user_id=session.user.id
        )

        refreshed = await auth_service.refresh(
            raw_refresh_token=session.raw_refresh_token
        )
        assert refreshed.membership.permissions_version == 1

        claims = await all_services["token_service"].verify_access_token(
            token=refreshed.access_token
        )
        assert claims.permissions_version == 1

    async def test_invalid_token_propagates(self, auth_service):
        with pytest.raises(InvalidRefreshTokenError):
            await auth_service.refresh(raw_refresh_token="not-a-real-token")

    async def test_reused_token_propagates_reuse_detected(self, auth_service):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        await auth_service.refresh(raw_refresh_token=session.raw_refresh_token)

        # Reusing the OLD (now-rotated) token — the actual theft scenario.
        with pytest.raises(RefreshTokenReuseDetectedError):
            await auth_service.refresh(raw_refresh_token=session.raw_refresh_token)

    async def test_missing_membership_revokes_family_and_raises(
        self, auth_service, all_services
    ):
        """Constructed through public APIs: RefreshTokenService.issue()
        doesn't check that a membership exists for the (user_id,
        tenant_id) pair, so a refresh token can legitimately exist with
        no corresponding membership at all.

        Also verifies the compensating revoke invalidates the entire
        family, not just the token that was checked — see the inline
        comment below."""
        user = await all_services["user_service"].create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        tenant = await all_services["tenant_service"].create(
            tenant_label="No Membership Here"
        )
        _record, raw_refresh_token = await all_services["refresh_token_service"].issue(
            user_id=user.id, tenant_id=tenant.id
        )

        with pytest.raises(NoActiveMembershipError):
            await auth_service.refresh(raw_refresh_token=raw_refresh_token)

        # The compensating revoke must invalidate the entire refresh-
        # token family. Reusing the original token afterwards should
        # therefore fail as an invalid token rather than remaining in
        # a reusable rotated state.
        with pytest.raises(InvalidRefreshTokenError):
            await auth_service.refresh(raw_refresh_token=raw_refresh_token)

    async def test_missing_user_raises_invariant_error(
        self, auth_service, all_services
    ):
        """A different invariant from the missing-membership case above
        — here the membership genuinely exists and is active, but the
        user_id it (and the refresh token) references was never
        actually created. Constructed through public APIs: none of
        RefreshTokenService.issue(), MembershipService.create() check
        that user_id refers to a real user."""
        fake_user_id = uuid4()
        tenant = await all_services["tenant_service"].create(
            tenant_label="Some Business"
        )
        await all_services["membership_service"].create(
            user_id=fake_user_id, tenant_id=tenant.id, role=Role.OWNER
        )
        _record, raw_refresh_token = await all_services["refresh_token_service"].issue(
            user_id=fake_user_id, tenant_id=tenant.id
        )

        with pytest.raises(IdentityInvariantError):
            await auth_service.refresh(raw_refresh_token=raw_refresh_token)

    async def test_missing_tenant_raises_invariant_error(
        self, auth_service, all_services
    ):
        """Symmetric to the missing-user case — the membership is
        active and references a real user, but the tenant_id it (and
        the refresh token) references was never actually created."""
        user = await all_services["user_service"].create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        fake_tenant_id = uuid4()
        await all_services["membership_service"].create(
            user_id=user.id, tenant_id=fake_tenant_id, role=Role.OWNER
        )
        _record, raw_refresh_token = await all_services["refresh_token_service"].issue(
            user_id=user.id, tenant_id=fake_tenant_id
        )

        with pytest.raises(IdentityInvariantError):
            await auth_service.refresh(raw_refresh_token=raw_refresh_token)


class TestLogout:
    pytestmark = pytest.mark.asyncio

    async def test_revokes_the_session(self, auth_service):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )

        await auth_service.logout(raw_refresh_token=session.raw_refresh_token)

        with pytest.raises(InvalidRefreshTokenError):
            await auth_service.refresh(raw_refresh_token=session.raw_refresh_token)

    async def test_is_idempotent_for_unknown_token(self, auth_service):
        await auth_service.logout(raw_refresh_token="never-issued")  # no raise


class TestLogoutAllForTenant:
    pytestmark = pytest.mark.asyncio

    async def test_revokes_all_sessions_for_tenant_only(
        self, auth_service, all_services
    ):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        # A second session (device) for the same user, same tenant.
        await all_services["refresh_token_service"].issue(
            user_id=session.user.id, tenant_id=session.tenant.id
        )
        # A session in a DIFFERENT tenant for the same user — must be
        # left untouched.
        other_tenant = await all_services["tenant_service"].create(
            tenant_label="Second Business"
        )
        await all_services["membership_service"].create(
            user_id=session.user.id, tenant_id=other_tenant.id, role=Role.TECHNICIAN
        )
        _, other_tenant_raw_token = await all_services["refresh_token_service"].issue(
            user_id=session.user.id, tenant_id=other_tenant.id
        )

        count = await auth_service.logout_all_for_tenant(
            user_id=session.user.id, tenant_id=session.tenant.id
        )
        assert count == 2  # the signup session + the second device session

        with pytest.raises(InvalidRefreshTokenError):
            await auth_service.refresh(raw_refresh_token=session.raw_refresh_token)

        # Untouched — a subsequent refresh in the OTHER tenant must
        # still succeed.
        refreshed = await auth_service.refresh(raw_refresh_token=other_tenant_raw_token)
        assert refreshed.tenant.id == other_tenant.id


class TestVerifyEmail:
    pytestmark = pytest.mark.asyncio

    async def test_marks_user_verified_and_bumps_permissions_version(
        self, auth_service, email_sender
    ):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        assert session.user.email_verified is False
        raw_token = email_sender.last_verification_token_by_email["dana@example.com"]

        await auth_service.verify_email(raw_token=raw_token)

        # verify_email() returns None — confirm the effects via a fresh
        # refresh(), which does its own independent membership/user
        # lookup, proving the changes actually persisted rather than
        # trusting a return value that doesn't exist.
        refreshed = await auth_service.refresh(
            raw_refresh_token=session.raw_refresh_token
        )
        assert refreshed.user.email_verified is True
        assert refreshed.membership.permissions_version == 1

    async def test_does_not_invalidate_existing_session(
        self, auth_service, all_services, email_sender
    ):
        """Invariant 15: verifying an email must never invalidate an
        existing session. The ORIGINAL access token, issued before
        verification, must still verify successfully afterward — and
        still carries the OLD permissions_version, since new
        permissions apply from the next refresh() onward, not
        immediately."""
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        raw_token = email_sender.last_verification_token_by_email["dana@example.com"]

        await auth_service.verify_email(raw_token=raw_token)

        claims = await all_services["token_service"].verify_access_token(
            token=session.access_token
        )
        assert claims.permissions_version == 0

    async def test_invalid_token_propagates(self, auth_service):
        with pytest.raises(VerificationTokenInvalidError):
            await auth_service.verify_email(raw_token="not-a-real-token")

    async def test_already_consumed_token_propagates(self, auth_service, email_sender):
        await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        raw_token = email_sender.last_verification_token_by_email["dana@example.com"]
        await auth_service.verify_email(raw_token=raw_token)

        with pytest.raises(VerificationTokenInvalidError):
            await auth_service.verify_email(raw_token=raw_token)


class TestResendVerificationEmail:
    pytestmark = pytest.mark.asyncio

    async def test_sends_new_token_and_invalidates_old(
        self, auth_service, email_sender
    ):
        session = await auth_service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        old_raw_token = email_sender.last_verification_token_by_email[
            "dana@example.com"
        ]

        await auth_service.resend_verification_email(user_id=session.user.id)

        new_raw_token = email_sender.last_verification_token_by_email[
            "dana@example.com"
        ]
        assert new_raw_token != old_raw_token

        with pytest.raises(VerificationTokenInvalidError):
            await auth_service.verify_email(raw_token=old_raw_token)

        await auth_service.verify_email(raw_token=new_raw_token)  # does not raise

    async def test_missing_user_raises_invariant_error(self, auth_service):
        with pytest.raises(IdentityInvariantError):
            await auth_service.resend_verification_email(user_id=uuid4())

    async def test_email_delivery_failure_propagates(self, all_services):
        """Unlike signup(), resend's delivery failure must NOT be
        suppressed — the operation's entire purpose is sending this one
        email, so the caller needs to know it failed."""

        class _FailingEmailSender:
            async def send_verification_email(self, *, to: str, raw_token: str) -> None:
                raise ConnectionError("simulated delivery failure")

            async def send_invitation_email(
                self, *, to: str, raw_token: str, tenant: Tenant, invited_by: User
            ) -> None:
                pass

        service = AuthService(email_sender=_FailingEmailSender(), **all_services)
        session = await service.signup(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )  # signup itself succeeds despite the failing sender (suppressed there)

        with pytest.raises(ConnectionError):
            await service.resend_verification_email(user_id=session.user.id)


class TestCreateInvite:
    pytestmark = pytest.mark.asyncio

    async def _verified_owner_session(self, auth_service, email_sender):
        """Shared setup: an owner whose email has been verified — a
        freshly-signed-up owner is NOT yet verified, and
        members:invite is a soft-gated permission (PermissionService),
        so an unverified owner would fail the permission check for the
        wrong reason (soft gate, not role)."""
        session = await auth_service.signup(
            email="owner@example.com",
            password="hunter2",
            display_name="Owner",
            tenant_label="Owner's Business",
        )
        raw_token = email_sender.last_verification_token_by_email["owner@example.com"]
        await auth_service.verify_email(raw_token=raw_token)
        return session

    async def test_successful_invite_creation(self, auth_service, email_sender):
        session = await self._verified_owner_session(auth_service, email_sender)

        invitation = await auth_service.create_invite(
            tenant_id=session.tenant.id,
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=session.user.id,
        )

        assert invitation.email == "new.tech@example.com"
        assert invitation.role == Role.TECHNICIAN
        assert "new.tech@example.com" in email_sender.invitation_emails_sent

    async def test_permission_denied_for_technician(
        self, auth_service, all_services, email_sender
    ):
        session = await self._verified_owner_session(auth_service, email_sender)
        # A second, verified-irrelevant technician in the same tenant —
        # technicians don't have members:invite regardless of
        # verification status.
        technician_session = await auth_service.signup(
            email="tech@example.com",
            password="hunter2",
            display_name="Tech",
            tenant_label="Irrelevant",
        )
        await all_services["membership_service"].create(
            user_id=technician_session.user.id,
            tenant_id=session.tenant.id,
            role=Role.TECHNICIAN,
        )

        with pytest.raises(PermissionDeniedError):
            await auth_service.create_invite(
                tenant_id=session.tenant.id,
                email="new.tech@example.com",
                role=Role.TECHNICIAN,
                invited_by_user_id=technician_session.user.id,
            )

    async def test_inviter_without_active_membership_raises(
        self, auth_service, email_sender
    ):
        session = await self._verified_owner_session(auth_service, email_sender)
        unrelated_session = await auth_service.signup(
            email="unrelated@example.com",
            password="hunter2",
            display_name="Unrelated",
            tenant_label="Somewhere Else",
        )

        with pytest.raises(NoActiveMembershipError):
            await auth_service.create_invite(
                tenant_id=session.tenant.id,
                email="new.tech@example.com",
                role=Role.TECHNICIAN,
                invited_by_user_id=unrelated_session.user.id,
            )

    async def test_already_member_raises(
        self, auth_service, all_services, email_sender
    ):
        session = await self._verified_owner_session(auth_service, email_sender)
        existing_member_session = await auth_service.signup(
            email="already.here@example.com",
            password="hunter2",
            display_name="Already Here",
            tenant_label="Somewhere Else",
        )
        await all_services["membership_service"].create(
            user_id=existing_member_session.user.id,
            tenant_id=session.tenant.id,
            role=Role.TECHNICIAN,
        )

        with pytest.raises(AlreadyAMemberError):
            await auth_service.create_invite(
                tenant_id=session.tenant.id,
                email="already.here@example.com",
                role=Role.TECHNICIAN,
                invited_by_user_id=session.user.id,
            )

    async def test_email_delivery_failure_propagates(self, all_services, email_sender):
        """Unlike signup(), invite delivery failure must NOT be
        suppressed — Invitation has no resend capability, so a
        suppressed failure would leave a permanently orphaned,
        undiscoverable invitation."""

        class _FailingInviteSender:
            async def send_verification_email(self, *, to: str, raw_token: str) -> None:
                pass

            async def send_invitation_email(
                self, *, to: str, raw_token: str, tenant: Tenant, invited_by: User
            ) -> None:
                raise ConnectionError("simulated delivery failure")

        working_sender = _NoopEmailSender()
        service_with_working_sender = AuthService(
            email_sender=working_sender, **all_services
        )
        owner_session = await service_with_working_sender.signup(
            email="owner@example.com",
            password="hunter2",
            display_name="Owner",
            tenant_label="Owner's Business",
        )
        owner_raw_token = working_sender.last_verification_token_by_email[
            "owner@example.com"
        ]
        await service_with_working_sender.verify_email(raw_token=owner_raw_token)

        service_with_failing_sender = AuthService(
            email_sender=_FailingInviteSender(), **all_services
        )
        with pytest.raises(ConnectionError):
            await service_with_failing_sender.create_invite(
                tenant_id=owner_session.tenant.id,
                email="new.tech@example.com",
                role=Role.TECHNICIAN,
                invited_by_user_id=owner_session.user.id,
            )


class TestAcceptInviteExistingUser:
    pytestmark = pytest.mark.asyncio

    async def test_successful_acceptance_adds_membership_without_new_session(
        self, auth_service, all_services
    ):
        owner_session = await auth_service.signup(
            email="owner@example.com",
            password="hunter2",
            display_name="Owner",
            tenant_label="Owner's Business",
        )
        invitee_session = await auth_service.signup(
            email="invitee@example.com",
            password="hunter2",
            display_name="Invitee",
            tenant_label="Invitee's Own Business",
        )
        # Constructed via InvitationService directly for raw-token
        # access — _NoopEmailSender only tracks recipients for
        # invitation emails, not the token itself (unlike verification
        # emails, which are needed by many more tests and were worth
        # the extra tracking).
        _invitation, raw_invite_token = await all_services["invitation_service"].create(
            tenant_id=owner_session.tenant.id,
            email="invitee@example.com",
            role=Role.DISPATCHER,
            invited_by_user_id=owner_session.user.id,
        )

        result = await auth_service.accept_invite_existing_user(
            raw_token=raw_invite_token,
            authenticated_user_id=invitee_session.user.id,
        )

        assert result.tenant.id == owner_session.tenant.id
        assert result.membership.role == Role.DISPATCHER
        assert result.membership.user_id == invitee_session.user.id
        assert result.invitation.status.value == "accepted"

        # No new session was minted — the invitee's ORIGINAL refresh
        # token (from their own signup) must still work, and their
        # active tenant context must be unchanged; accepting an invite
        # must not silently switch it.
        refreshed = await auth_service.refresh(
            raw_refresh_token=invitee_session.raw_refresh_token
        )
        assert refreshed.tenant.id == invitee_session.tenant.id

    async def test_email_mismatch_raises(self, auth_service, all_services):
        owner_session = await auth_service.signup(
            email="owner@example.com",
            password="hunter2",
            display_name="Owner",
            tenant_label="Owner's Business",
        )
        _invitation, raw_invite_token = await all_services["invitation_service"].create(
            tenant_id=owner_session.tenant.id,
            email="intended@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=owner_session.user.id,
        )
        someone_else_session = await auth_service.signup(
            email="someone.else@example.com",
            password="hunter2",
            display_name="Someone Else",
            tenant_label="Different Business",
        )

        with pytest.raises(InvitationEmailMismatchError):
            await auth_service.accept_invite_existing_user(
                raw_token=raw_invite_token,
                authenticated_user_id=someone_else_session.user.id,
            )

    async def test_invalid_token_propagates(self, auth_service):
        with pytest.raises(InvitationInvalidError):
            await auth_service.accept_invite_existing_user(
                raw_token="not-a-real-token", authenticated_user_id=uuid4()
            )


class TestAcceptInviteNewUser:
    pytestmark = pytest.mark.asyncio

    async def test_successful_acceptance_creates_verified_user_and_session(
        self, auth_service, all_services
    ):
        owner_session = await auth_service.signup(
            email="owner@example.com",
            password="hunter2",
            display_name="Owner",
            tenant_label="Owner's Business",
        )
        invitation, raw_invite_token = await all_services["invitation_service"].create(
            tenant_id=owner_session.tenant.id,
            email="new.invitee@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=owner_session.user.id,
        )

        session = await auth_service.accept_invite_new_user(
            raw_token=raw_invite_token, password="hunter2", display_name="Invitee"
        )

        assert session.user.email == "new.invitee@example.com"
        assert session.user.email_verified is True  # Invariant 9
        assert session.tenant.id == owner_session.tenant.id
        assert session.membership.role == Role.TECHNICIAN
        assert session.access_token
        assert session.raw_refresh_token

    async def test_invalid_token_propagates(self, auth_service):
        with pytest.raises(InvitationInvalidError):
            await auth_service.accept_invite_new_user(
                raw_token="not-a-real-token",
                password="hunter2",
                display_name="Invitee",
            )

    async def test_duplicate_email_propagates(self, auth_service, all_services):
        owner_session = await auth_service.signup(
            email="owner@example.com",
            password="hunter2",
            display_name="Owner",
            tenant_label="Owner's Business",
        )
        await auth_service.signup(
            email="already.exists@example.com",
            password="hunter2",
            display_name="Existing",
            tenant_label="Somewhere Else",
        )
        invitation, raw_invite_token = await all_services["invitation_service"].create(
            tenant_id=owner_session.tenant.id,
            email="already.exists@example.com",
            role=Role.TECHNICIAN,
            invited_by_user_id=owner_session.user.id,
        )

        with pytest.raises(EmailAlreadyRegisteredError):
            await auth_service.accept_invite_new_user(
                raw_token=raw_invite_token, password="hunter2", display_name="Dupe"
            )


class TestConstruction:
    def test_constructs_with_all_dependencies(self, auth_service):
        assert isinstance(auth_service, AuthService)

    def test_stores_every_dependency_under_its_expected_attribute(
        self, auth_service, all_services, email_sender
    ):
        """Verifies DI wiring specifically — each constructor argument
        ends up stored under the private attribute name every method's
        docstring assumes it's accessible as, without touching any
        actual orchestration logic."""
        assert auth_service._user_service is all_services["user_service"]
        assert auth_service._tenant_service is all_services["tenant_service"]
        assert auth_service._membership_service is all_services["membership_service"]
        assert (
            auth_service._email_verification_service
            is all_services["email_verification_service"]
        )
        assert auth_service._invitation_service is all_services["invitation_service"]
        assert (
            auth_service._refresh_token_service is all_services["refresh_token_service"]
        )
        assert auth_service._token_service is all_services["token_service"]
        assert auth_service._permission_service is all_services["permission_service"]
        assert auth_service._email_sender is email_sender
