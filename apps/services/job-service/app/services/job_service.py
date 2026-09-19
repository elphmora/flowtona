"""
app/services/job_service.py

JobService -- the application/orchestration service for Job's own
business logic, matching client-service's established "entity service"
pattern (ClientService/SiteService/ContactService, one per aggregate).

Scope, precisely: permission checking (jobs:write, clients:read for
Create Job; jobs:read for Query Operations) is NOT performed here.
Authorization belongs to the API layer before JobService is invoked.
This class therefore trusts its caller to have authenticated and
authorized the request.

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
    JobNotFoundError,
    SiteNotFoundError,
    VisitNotFoundError,
)
from app.models.job import Job, JobStatus, SiteAddressSnapshot, Visit
from app.repositories.job_repository import JobPage, JobRepository
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
        """Create a Job after resolving and validating its Client
        reference. ClientNotFoundError and ServiceUnavailableError, if
        raised, come directly from ClientReader.get_client() -- not
        caught and re-raised here, since they're already the correct
        DomainError subclasses for this situation."""
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

    async def get_job(self, *, tenant_id: UUID, job_id: UUID) -> Job:
        """Query Operations checkpoint. Translates the repository's
        plain None into JobNotFoundError -- the repository's contract
        stays a boring lookup; domain meaning of "not found" lives
        here, matching the same layering already established for
        Create Job's own not-found translations."""
        job = await self._job_repository.get(tenant_id, job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    async def list_jobs(
        self,
        *,
        tenant_id: UUID,
        status: JobStatus | None = None,
        client_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JobPage:
        """Thin passthrough -- JobPage is already the shape both the
        route and this service want; no translation needed. limit/
        offset are expected already-normalized by the API/schema layer
        (default 20, max 100, clamped) before reaching here -- this
        service does not itself enforce that policy, matching
        client-service's own established repository/service boundary."""
        return await self._job_repository.list_by_tenant(
            tenant_id=tenant_id,
            status=status,
            client_id=client_id,
            limit=limit,
            offset=offset,
        )

    async def add_visit(self, *, tenant_id: UUID, job_id: UUID) -> Visit:
        """Create a draft Visit within an existing Job aggregate.

        The Job is resolved through get_job(), preserving the existing
        tenant-scoped not-found behavior. Job.add_visit() owns the
        aggregate's terminal-state invariant and raises JobTerminalError
        for completed or cancelled Jobs; this service deliberately does
        not duplicate that domain rule.

        The mutated aggregate is persisted through the repository's
        tenant-scoped save() operation, then the newly-created Visit is
        returned to the caller.
        """
        job = await self.get_job(tenant_id=tenant_id, job_id=job_id)

        visit = job.add_visit()

        await self._job_repository.save(tenant_id=tenant_id, job=job)

        return visit

    async def get_visit(
        self, *, tenant_id: UUID, job_id: UUID, visit_id: UUID
    ) -> Visit:
        """Tenant-scoped Job lookup happens first, via get_job() --
        raises JobNotFoundError exactly as that method already does.
        Only once the Job itself resolves does the Visit lookup run.

        Return type is Visit, now that Phase 2 gives it a real domain
        model. Because Job.visits is empty until a Visit is actually
        added via Job.add_visit(), this method still raises
        VisitNotFoundError for a visit_id that does not match a Visit
        belonging to the resolved Job.
        """
        job = await self.get_job(tenant_id=tenant_id, job_id=job_id)
        visit = next((v for v in job.visits if v.id == visit_id), None)

        if visit is None:
            raise VisitNotFoundError(visit_id)

        return visit
