"""
tests/unit/services/conftest.py
"""

import pytest

from app.repositories.in_memory import (
    InMemoryClientRepository,
    InMemoryContactRepository,
    InMemorySiteRepository,
    InMemoryStore,
)
from app.services.client_service import ClientService
from app.services.contact_service import ContactService
from app.services.site_service import SiteService


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


@pytest.fixture
def client_service(client_repo: InMemoryClientRepository) -> ClientService:
    return ClientService(client_repo)


@pytest.fixture
def site_service(
    site_repo: InMemorySiteRepository,
    contact_repo: InMemoryContactRepository,
    client_service: ClientService,
) -> SiteService:
    return SiteService(site_repo, contact_repo, client_service)


@pytest.fixture
def contact_service(
    contact_repo: InMemoryContactRepository, client_service: ClientService
) -> ContactService:
    return ContactService(contact_repo, client_service)
