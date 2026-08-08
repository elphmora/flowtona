"""
tests/unit/repositories/conftest.py
"""

import pytest

from app.repositories.in_memory import (
    InMemoryClientRepository,
    InMemoryContactRepository,
    InMemorySiteRepository,
    InMemoryStore,
)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def client_repo(store: InMemoryStore) -> InMemoryClientRepository:
    return InMemoryClientRepository(store)


@pytest.fixture
def site_repo(store: InMemoryStore) -> InMemorySiteRepository:
    return InMemorySiteRepository(store)


@pytest.fixture
def contact_repo(store: InMemoryStore) -> InMemoryContactRepository:
    return InMemoryContactRepository(store)
