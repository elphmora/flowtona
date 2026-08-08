"""
app/repositories/in_memory/store.py

Shared in-memory persistence boundary for the three client-service
repositories (Platform Conventions §4). One instance is passed into
every InMemory*Repository's constructor, so multi-repository workflows
(site deletion — 02-sequence-diagrams.md) share one consistent view of
state, matching identity-service's InMemoryIdentityStore pattern.

Named InMemoryStore, not InMemoryClientStore — "Client" is already an
entity name within this service, and prefixing the store with it would
read as if the store only held Clients.

Deliberately boring: explicit typed dict indexes per lookup pattern
actually needed, not a generic indexing framework — same convention as
identity-service's store.
"""

import asyncio
from dataclasses import dataclass, field
from uuid import UUID

from app.models.client import Client
from app.models.contact import Contact
from app.models.site import Site


@dataclass
class InMemoryStore:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    clients_by_id: dict[UUID, Client] = field(default_factory=dict)
    client_ids_by_tenant: dict[UUID, list[UUID]] = field(default_factory=dict)

    sites_by_id: dict[UUID, Site] = field(default_factory=dict)
    site_ids_by_client: dict[UUID, list[UUID]] = field(default_factory=dict)

    contacts_by_id: dict[UUID, Contact] = field(default_factory=dict)
    contact_ids_by_client: dict[UUID, list[UUID]] = field(default_factory=dict)
