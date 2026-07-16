"""
tests/unit/repositories/conftest.py

Fresh InMemoryIdentityStore + one instance of each repository per test —
shared store instance across the six fixtures, matching how they're
actually used together in real workflows (signup touches User, Tenant,
and Membership through one shared store).
"""

import pytest

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


@pytest.fixture
def store() -> InMemoryIdentityStore:
    return InMemoryIdentityStore()


@pytest.fixture
def user_repo(store: InMemoryIdentityStore) -> InMemoryUserRepository:
    return InMemoryUserRepository(store)


@pytest.fixture
def tenant_repo(store: InMemoryIdentityStore) -> InMemoryTenantRepository:
    return InMemoryTenantRepository(store)


@pytest.fixture
def membership_repo(store: InMemoryIdentityStore) -> InMemoryMembershipRepository:
    return InMemoryMembershipRepository(store)


@pytest.fixture
def email_verification_repo(
    store: InMemoryIdentityStore,
) -> InMemoryEmailVerificationRepository:
    return InMemoryEmailVerificationRepository(store)


@pytest.fixture
def invitation_repo(store: InMemoryIdentityStore) -> InMemoryInvitationRepository:
    return InMemoryInvitationRepository(store)


@pytest.fixture
def refresh_token_repo(store: InMemoryIdentityStore) -> InMemoryRefreshTokenRepository:
    return InMemoryRefreshTokenRepository(store)
