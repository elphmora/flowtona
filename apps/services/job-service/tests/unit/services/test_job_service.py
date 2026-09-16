"""
tests/unit/services/test_job_service.py

Uses a minimal hand-rolled fake satisfying JobService's ClientReader
Protocol. ClientServiceClient's own HTTP/retry mechanics are already
thoroughly tested in test_client_service_client.py; these tests are
about JobService's orchestration logic, so the fake just needs to
return a canned response or raise a canned exception per scenario,
and record what it was called with (to prove access_token forwarding).

The real InMemoryJobRepository is used directly rather than mocked --
it has no I/O and is already independently tested, so using it here
also proves create_job() genuinely persists, not just that it calls
create().
"""

from uuid import UUID, uuid4

import pytest

from app.exceptions.job import (
    ClientArchivedError,
    ClientNotFoundError,
    ContactNotFoundError,
    ServiceUnavailableError,
    SiteNotFoundError,
)
from app.repositories.in_memory.job_repository import InMemoryJobRepository
from app.services.client_service_client import (
    ClientContactResponse,
    ClientServiceResponse,
    ClientSiteResponse,
    SiteAddressResponse,
)
from app.services.job_service import JobService


class _FakeClientServiceClient:
    def __init__(
        self,
        *,
        response: ClientServiceResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[UUID, str]] = []

    async def get_client(
        self, client_id: UUID, access_token: str
    ) -> ClientServiceResponse:
        self.calls.append((client_id, access_token))
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _make_client_response(
    *,
    client_id: UUID | None = None,
    status: str = "active",
    site_id: UUID | None = None,
    contact_id: UUID | None = None,
    include_contact: bool = True,
) -> ClientServiceResponse:
    return ClientServiceResponse(
        id=client_id or uuid4(),
        name="Birmingham Plumbing Co.",
        status=status,
        sites=[
            ClientSiteResponse(
                id=site_id or uuid4(),
                label="Main Warehouse",
                address=SiteAddressResponse(
                    line1="14 Colmore Row",
                    line2=None,
                    city="Birmingham",
                    postcode="B3 2QD",
                    country=None,
                ),
            )
        ],
        contacts=[
            ClientContactResponse(
                id=contact_id or uuid4(),
                name="Priya Shah",
                email="priya@birminghamplumbing.co.uk",
                phone="+44 121 000 0000",
            )
        ]
        if include_contact
        else [],
    )


async def test_create_job_succeeds_and_persists() -> None:
    client_id = uuid4()
    site_id = uuid4()
    contact_id = uuid4()
    client_response = _make_client_response(
        client_id=client_id, site_id=site_id, contact_id=contact_id
    )
    fake_client = _FakeClientServiceClient(response=client_response)
    repository = InMemoryJobRepository()
    service = JobService(fake_client, repository)
    tenant_id = uuid4()

    job = await service.create_job(
        tenant_id=tenant_id,
        access_token="test-token",
        client_id=client_id,
        site_id=site_id,
        contact_id=contact_id,
        title="Annual boiler service",
        description="Client reports intermittent pilot light failure.",
    )

    assert job.client_id == client_id
    assert job.client_name_snapshot == "Birmingham Plumbing Co."

    assert job.site_id == site_id
    assert job.site_label_snapshot == "Main Warehouse"
    assert job.site_address_snapshot.line1 == "14 Colmore Row"
    assert job.site_address_snapshot.line2 is None
    assert job.site_address_snapshot.city == "Birmingham"
    assert job.site_address_snapshot.postcode == "B3 2QD"
    assert job.site_address_snapshot.country is None

    assert job.contact_id == contact_id
    assert job.contact_name_snapshot == "Priya Shah"
    assert job.contact_email_snapshot == "priya@birminghamplumbing.co.uk"
    assert job.contact_phone_snapshot == "+44 121 000 0000"

    persisted = await repository.get(tenant_id=tenant_id, job_id=job.id)
    assert persisted is not None
    assert persisted.title == "Annual boiler service"


async def test_create_job_forwards_access_token_unchanged() -> None:
    client_response = _make_client_response()
    fake_client = _FakeClientServiceClient(response=client_response)
    service = JobService(fake_client, InMemoryJobRepository())

    await service.create_job(
        tenant_id=uuid4(),
        access_token="the-exact-forwarded-token",
        client_id=client_response.id,
        site_id=client_response.sites[0].id,
        contact_id=None,
        title="Test job",
        description=None,
    )

    assert fake_client.calls == [(client_response.id, "the-exact-forwarded-token")]


async def test_create_job_succeeds_without_a_contact() -> None:
    client_response = _make_client_response(include_contact=False)
    fake_client = _FakeClientServiceClient(response=client_response)
    service = JobService(fake_client, InMemoryJobRepository())

    job = await service.create_job(
        tenant_id=uuid4(),
        access_token="test-token",
        client_id=client_response.id,
        site_id=client_response.sites[0].id,
        contact_id=None,
        title="Test job",
        description=None,
    )

    assert job.contact_id is None
    assert job.contact_name_snapshot is None
    assert job.contact_email_snapshot is None
    assert job.contact_phone_snapshot is None


async def test_create_job_propagates_client_not_found() -> None:
    client_id = uuid4()
    fake_client = _FakeClientServiceClient(error=ClientNotFoundError(client_id))
    service = JobService(fake_client, InMemoryJobRepository())

    with pytest.raises(ClientNotFoundError):
        await service.create_job(
            tenant_id=uuid4(),
            access_token="t",
            client_id=client_id,
            site_id=uuid4(),
            contact_id=None,
            title="Test job",
            description=None,
        )


async def test_create_job_propagates_service_unavailable() -> None:
    fake_client = _FakeClientServiceClient(error=ServiceUnavailableError())
    service = JobService(fake_client, InMemoryJobRepository())

    with pytest.raises(ServiceUnavailableError):
        await service.create_job(
            tenant_id=uuid4(),
            access_token="t",
            client_id=uuid4(),
            site_id=uuid4(),
            contact_id=None,
            title="Test job",
            description=None,
        )


async def test_create_job_rejects_archived_client() -> None:
    client_response = _make_client_response(status="archived")
    fake_client = _FakeClientServiceClient(response=client_response)
    service = JobService(fake_client, InMemoryJobRepository())

    with pytest.raises(ClientArchivedError):
        await service.create_job(
            tenant_id=uuid4(),
            access_token="t",
            client_id=client_response.id,
            site_id=client_response.sites[0].id,
            contact_id=None,
            title="Test job",
            description=None,
        )


async def test_create_job_rejects_unknown_site() -> None:
    client_response = _make_client_response()
    fake_client = _FakeClientServiceClient(response=client_response)
    service = JobService(fake_client, InMemoryJobRepository())

    with pytest.raises(SiteNotFoundError):
        await service.create_job(
            tenant_id=uuid4(),
            access_token="t",
            client_id=client_response.id,
            site_id=uuid4(),  # does not match client_response's one site
            contact_id=None,
            title="Test job",
            description=None,
        )


async def test_create_job_rejects_unknown_contact() -> None:
    client_response = _make_client_response()
    fake_client = _FakeClientServiceClient(response=client_response)
    service = JobService(fake_client, InMemoryJobRepository())

    with pytest.raises(ContactNotFoundError):
        await service.create_job(
            tenant_id=uuid4(),
            access_token="t",
            client_id=client_response.id,
            site_id=client_response.sites[0].id,
            contact_id=uuid4(),  # does not match client_response's one contact
            title="Test job",
            description=None,
        )
