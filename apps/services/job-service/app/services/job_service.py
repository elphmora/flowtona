"""
app/services/job_service.py

JobService -- the application/orchestration service for Job's own
business logic, matching client-service's established "entity service"
pattern (ClientService/SiteService/ContactService, one per aggregate).

Scope, precisely: permission checking (jobs:write, clients:read) is
NOT here -- 01-create-job.md's diagram draws that as an API-layer
self-call, happening before JobService.create_job() is ever invoked,
not something this class does internally. There's also no JWT/auth
dependency built yet to check permissions against. That lands in the
next checkpoint, alongside the route itself. This class trusts its
caller has already verified both permissions.

ClientReader is a consumer-owned Protocol, not a dependency on the
concrete ClientServiceClient adapter class -- matching JobRepository's
own established Protocol pattern (Platform Conventions §4). JobService
is the consumer, so it defines the tiny interface it actually needs,
here, not in app/services/client_service_client.py -- putting it there
would make the port look adapter-owned rather than consumer-owned.
This also makes the dependency direction explicit and correctly typed:
    JobService -> ClientReader (port) <- ClientServiceClient (adapter)
rather than JobService depending directly on the HTTP adapter class.

validate_client_reference() is deliberately not underscore-prefixed --
01-create-job.md's Notes explicitly frame it as reusable machinery
("every future endpoint that references a Client/Site/Contact calls
this same method"), so it's named and shaped as a stable, testable
piece of this class's contract, not an incidental private helper.
It returns the matched site/contact objects (not just validates and
discards them) -- create_job() needs them immediately after for
snapshot construction, and returning them avoids a second lookup over
the same already-fetched lists. The sequence diagrams don't specify a
return value for this method; this is a deliberate implementation
choice, not something copied from a frozen contract.

access_token is threaded through explicitly, end to end -- extracted
by whatever calls create_job() (the route, once built) from the
verified JWT, forwarded unchanged into ClientReader.get_client() --
never read from anywhere implicit, matching Decision 2's explicit-
parameter-threading discipline applied throughout this project.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.exceptions.job import (
    ClientArchivedError,
    ContactNotFoundError,
    SiteNotFoundError,
)
from app.models.job import Job, SiteAddressSnapshot
from app.repositories.job_repository import JobRepository
from app.services.client_service_client import (
    ClientContactResponse,
    ClientServiceResponse,
    ClientSiteResponse,
)


class ClientReader(Protocol):
    """The tiny interface JobService actually needs from whatever
    fetches Client data -- satisfied structurally by
    ClientServiceClient (and, in tests, by a minimal fake with no
    inheritance relationship to it)."""

    async def get_client(
        self, client_id: UUID, access_token: str
    ) -> ClientServiceResponse: ...


class JobService:
    def __init__(
        self,
        client_service_client: ClientReader,
        job_repository: JobRepository,
    ) -> None:
        self._client_service_client = client_service_client
        self._job_repository = job_repository

    def validate_client_reference(
        self,
        client: ClientServiceResponse,
        site_id: UUID,
        contact_id: UUID | None,
    ) -> tuple[ClientSiteResponse, ClientContactResponse | None]:
        """Archived check, site existence, contact existence -- all
        decided locally from the already-fetched client, never a
        further network call. Raises ClientArchivedError,
        SiteNotFoundError, or ContactNotFoundError; returns the
        matched (site, contact) pair on success. contact is None only
        when contact_id itself was None -- a genuinely absent contact
        reference is not an error (03-api-contract.md: contact_id is
        optional on Create Job)."""
        if client.status == "archived":
            raise ClientArchivedError(client.id)

        site = next((s for s in client.sites if s.id == site_id), None)
        if site is None:
            raise SiteNotFoundError(site_id)

        contact: ClientContactResponse | None = None
        if contact_id is not None:
            contact = next((c for c in client.contacts if c.id == contact_id), None)
            if contact is None:
                raise ContactNotFoundError(contact_id)

        return site, contact

    async def create_job(
        self,
        *,
        tenant_id: UUID,
        access_token: str,
        client_id: UUID,
        site_id: UUID,
        contact_id: UUID | None,
        title: str,
        description: str | None,
    ) -> Job:
        """The only command this checkpoint builds. ClientNotFoundError
        and ServiceUnavailableError, if raised, come directly from
        ClientReader.get_client() -- not caught and re-raised here,
        since they're already the correct DomainError subclasses for
        this situation."""
        client = await self._client_service_client.get_client(client_id, access_token)

        site, contact = self.validate_client_reference(client, site_id, contact_id)

        job = Job.create(
            tenant_id=tenant_id,
            client_id=client.id,
            client_name_snapshot=client.name,
            site_id=site.id,
            site_label_snapshot=site.label,
            site_address_snapshot=SiteAddressSnapshot(
                line1=site.address.line1,
                line2=site.address.line2,
                city=site.address.city,
                postcode=site.address.postcode,
                country=site.address.country,
            ),
            title=title,
            description=description,
            contact_id=contact.id if contact else None,
            contact_name_snapshot=contact.name if contact else None,
            contact_email_snapshot=contact.email if contact else None,
            contact_phone_snapshot=contact.phone if contact else None,
        )

        await self._job_repository.create(job)
        return job
