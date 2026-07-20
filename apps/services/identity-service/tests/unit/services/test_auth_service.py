"""tests/unit/services/test_auth_service.py

Unit tests for AuthService's authentication workflows.

Covers:
- signup()
- login()
- select_tenant()
- constructor/DI wiring

The remaining workflows (refresh, logout, logout_all_for_tenant, email
verification, invitations) are intentionally implemented and tested in
subsequent PRs.
"""

from uuid import uuid4

import pytest

from app.constants.roles import Role
from app.exceptions.auth import InvalidCredentialsError, NoActiveMembershipError
from app.exceptions.base import IdentityInvariantError
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
    backend."""

    def __init__(self) -> None:
        self.verification_emails_sent: list[str] = []
        self.invitation_emails_sent: list[str] = []

    async def send_verification_email(self, *, to: str, raw_token: str) -> None:
        self.verification_emails_sent.append(to)

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
