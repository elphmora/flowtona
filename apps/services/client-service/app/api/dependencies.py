"""
app/api/dependencies.py

Builds the shared service graph once (see build_services(), called
from main.py's lifespan handler at startup) and exposes FastAPI
dependency providers routes use via Depends() — routes never construct
services themselves.

The whole ServiceRegistry is stored as a single app.state.services
attribute (not unpacked into three flat app.state attributes) —
preserves the grouping ServiceRegistry already represents rather than
discarding it the moment it reaches app.state. Dependency providers
below read request.app.state.services.<name>, not
request.app.state.<name> directly.

One InMemoryStore shared across all three repositories — same pattern
as identity-service's InMemoryIdentityStore, one store instance per
process, matching every test in this codebase already doing the same
thing once per test instead of once per process.

TokenVerifier deliberately lives OUTSIDE ServiceRegistry, not as a
fourth entry alongside the three entity services — it isn't orchestrated
by any of them, it's request-level infrastructure (closer to
identity-service's own SecretProvider than to a domain service).
Constructed and attached to app.state.token_verifier separately in
main.py's lifespan — its own flat attribute, not nested under
app.state.services, since it isn't part of that grouping.
"""

from dataclasses import dataclass

from fastapi import Request

from app.repositories.in_memory import (
    InMemoryClientRepository,
    InMemoryContactRepository,
    InMemorySiteRepository,
    InMemoryStore,
)
from app.services.client_service import ClientService
from app.services.contact_service import ContactService
from app.services.site_service import SiteService


@dataclass(frozen=True, slots=True)
class ServiceRegistry:
    client_service: ClientService
    site_service: SiteService
    contact_service: ContactService


def build_services() -> ServiceRegistry:
    """Build the application's full service object graph. Unlike
    identity-service's build_services(settings), this takes no
    settings parameter — none of client-service's three entity
    services currently need any configuration value, only their
    repository. Add the parameter back if that stops being true,
    rather than threading an unused settings object through now."""

    # --- Repositories (one shared store) ---
    store = InMemoryStore()
    client_repo = InMemoryClientRepository(store)
    site_repo = InMemorySiteRepository(store)
    contact_repo = InMemoryContactRepository(store)

    # --- Domain services ---
    client_service = ClientService(client_repo)
    site_service = SiteService(site_repo, contact_repo, client_service)
    contact_service = ContactService(contact_repo, client_service)

    return ServiceRegistry(
        client_service=client_service,
        site_service=site_service,
        contact_service=contact_service,
    )


def get_client_service(request: Request) -> ClientService:
    return request.app.state.services.client_service


def get_site_service(request: Request) -> SiteService:
    return request.app.state.services.site_service


def get_contact_service(request: Request) -> ContactService:
    return request.app.state.services.contact_service
