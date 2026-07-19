"""tests/unit/services/test_auth_service.py

PR 1 (skeleton) coverage — constructor/DI wiring only. mypy already
catches signature mistakes in the (currently NotImplementedError) stub
methods statically; behavioral tests for each method land in the
follow-up PR that actually implements it, since tests that only assert
NotImplementedError provide no lasting regression protection and
disappear the moment real behavior lands.
"""

import pytest

from app.security.secret_provider import FileSecretProvider
from app.services.auth_email_sender import AuthEmailSender
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

pytestmark = pytest.mark.asyncio


class _NoopEmailSender:
    """Stand-in AuthEmailSender for tests — no real implementation
    exists yet (see auth_email_sender.py's module docstring)."""

    async def send_verification_email(self, *, to: str, raw_token: str) -> None:
        pass

    async def send_invitation_email(self, *, to, raw_token, tenant, invited_by) -> None:
        pass


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


class TestConstruction:
    async def test_constructs_with_all_dependencies(self, auth_service):
        assert isinstance(auth_service, AuthService)

    async def test_stores_every_dependency_under_its_expected_attribute(
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
