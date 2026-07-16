

"""
tests/unit/services/conftest.py

Services are tested against the real InMemoryUserRepository (not a
mock) — it's already independently tested (tests/unit/repositories/),
so using it here tests UserService's actual behavior end to end rather
than testing against assumptions about what the repository does.
"""

import pytest

from app.repositories.in_memory.store import InMemoryIdentityStore
from app.repositories.in_memory.user_repository import InMemoryUserRepository


@pytest.fixture
def store() -> InMemoryIdentityStore:
    return InMemoryIdentityStore()


@pytest.fixture
def user_repo(store: InMemoryIdentityStore) -> InMemoryUserRepository:
    return InMemoryUserRepository(store)