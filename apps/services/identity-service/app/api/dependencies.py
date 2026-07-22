"""
app/api/dependencies.py

Builds the shared service graph once (see build_services(), called
from main.py's lifespan handler at startup) and exposes FastAPI
dependency providers that route handlers use via Depends() — routes
never construct services themselves.

One InMemoryIdentityStore shared across every repository, exactly like
every test in this codebase already does — the only difference is this
happens once at process startup instead of once per test.

ServiceRegistry holds every constructed service, not just AuthService
— needed so a dependency like get_token_service() can read TokenService
directly from app.state, rather than reaching into AuthService's
private _token_service attribute (a real encapsulation violation).
build_auth_service() stays as a thin wrapper around build_services()
specifically so its existing signature/behavior/tests are unaffected
by this — it's not being replaced, just no longer the only thing this
module can produce.
"""

from dataclasses import dataclass

from fastapi import Request

from app.core.config import Settings
from app.repositories.in_memory.email_verification_repository import (
    InMemoryEmailVerificationRepository,
)
from app.repositories.in_memory.invitation_repository import (
    InMemoryInvitationRepository,
)
from app.repositories.in_memory.membership_repository import (
    InMemoryMembershipRepository,
)
from app.repositories.in_memory.refresh_token_repository import (
    InMemoryRefreshTokenRepository,
)
from app.repositories.in_memory.store import InMemoryIdentityStore
from app.repositories.in_memory.tenant_repository import InMemoryTenantRepository
from app.repositories.in_memory.user_repository import InMemoryUserRepository
from app.security.secret_provider import FileSecretProvider
from app.services.auth_service import AuthService
from app.services.email_verification_service import EmailVerificationService
from app.services.invitation_service import InvitationService
from app.services.logging_email_sender import LoggingEmailSender
from app.services.membership_service import MembershipService
from app.services.permission_service import PermissionService
from app.services.refresh_token_service import RefreshTokenService
from app.services.tenant_service import TenantService
from app.services.token_service import TokenService
from app.services.user_service import UserService


@dataclass(frozen=True, slots=True)
class ServiceRegistry:
    user_service: UserService
    tenant_service: TenantService
    membership_service: MembershipService
    email_verification_service: EmailVerificationService
    invitation_service: InvitationService
    refresh_token_service: RefreshTokenService
    token_service: TokenService
    permission_service: PermissionService
    auth_service: AuthService


# build_services() takes `settings` as an explicit parameter rather
# than importing the global `settings` singleton (the pattern every
# other service in this codebase correctly uses) — this function's
# whole purpose is being directly unit-testable with a DIFFERENT
# settings instance than production's (e.g. a tmp_path-based
# SECRETS_DIR for test isolation). Not an inconsistency with that
# established pattern — a different boundary: this is object-graph
# assembly, not a service consuming configuration.
#
# Grouped into sections (repositories -> infrastructure -> domain
# services -> orchestration) — one function for now, not split into
# separate helpers, since eight services still reads fine as one
# block. Worth splitting once this grows toward fifteen-plus services.
def build_services(settings: Settings) -> ServiceRegistry:
    """Build the application's full service object graph."""

    # --- Repositories (one shared store) ---
    store = InMemoryIdentityStore()
    user_repo = InMemoryUserRepository(store)
    tenant_repo = InMemoryTenantRepository(store)
    membership_repo = InMemoryMembershipRepository(store)
    email_verification_repo = InMemoryEmailVerificationRepository(store)
    invitation_repo = InMemoryInvitationRepository(store)
    refresh_token_repo = InMemoryRefreshTokenRepository(store)

    # --- Infrastructure ---
    secret_provider = FileSecretProvider(secrets_dir=settings.SECRETS_DIR)

    # --- Domain services ---
    user_service = UserService(user_repo)
    tenant_service = TenantService(tenant_repo)
    membership_service = MembershipService(membership_repo)
    email_verification_service = EmailVerificationService(email_verification_repo)
    invitation_service = InvitationService(invitation_repo)
    refresh_token_service = RefreshTokenService(refresh_token_repo)
    token_service = TokenService(secret_provider)
    permission_service = PermissionService()
    email_sender = LoggingEmailSender()

    # --- Orchestration ---
    auth_service = AuthService(
        user_service=user_service,
        tenant_service=tenant_service,
        membership_service=membership_service,
        email_verification_service=email_verification_service,
        invitation_service=invitation_service,
        refresh_token_service=refresh_token_service,
        token_service=token_service,
        permission_service=permission_service,
        email_sender=email_sender,
    )

    return ServiceRegistry(
        user_service=user_service,
        tenant_service=tenant_service,
        membership_service=membership_service,
        email_verification_service=email_verification_service,
        invitation_service=invitation_service,
        refresh_token_service=refresh_token_service,
        token_service=token_service,
        permission_service=permission_service,
        auth_service=auth_service,
    )


def build_auth_service(settings: Settings) -> AuthService:
    """Build just the AuthService — a thin wrapper around
    build_services(), preserved as its own function since existing
    tests and callers already depend on this exact signature."""
    return build_services(settings).auth_service


def get_auth_service(request: Request) -> AuthService:
    """Return the AuthService stored on application state."""
    return request.app.state.auth_service


def get_token_service(request: Request) -> TokenService:
    """Return the TokenService stored on application state."""
    return request.app.state.token_service
