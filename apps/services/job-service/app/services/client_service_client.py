"""
app/services/client_service_client.py

ClientServiceClient -- the platform's first real internal service-to-
service call (job-service -> client-service), per
platform-conventions.md §11 Amendment 7 and 01-create-job.md's
sequence diagram.

Scope, precisely: owns exactly the network call and its own error
translation -- ClientNotFoundError (404) and ServiceUnavailableError
(transport failure surviving one retry, or any other non-200/404
response). It does NOT own archived/site/contact validation --
01-create-job.md's diagram shows that as a separate JobService self-
call (validate_client_reference()), inspecting the already-fetched
response locally. That lands alongside JobService.create_job() in the
next checkpoint.

Amendment 7, implemented exactly:
  - The caller's own verified JWT is forwarded UNCHANGED -- never a
    separate service credential.
  - 2s timeout by default (DD-009: an explicit placeholder).
  - Exactly one retry, and ONLY on a transport-level failure
    (httpx.TransportError and its subclasses -- connection refused,
    DNS failure, timeouts) -- never on a completed HTTP response, even
    a 5xx one. A 5xx is a completed response from Client Service's own
    perspective; retrying it would be "ask twice and hope," which
    Amendment 7 doesn't permit.
  - No circuit breaker (Phase 1 scope).

`transport` is an injectable constructor parameter specifically for
testing (httpx.MockTransport) -- production code leaves it as None,
which makes httpx use its real default transport.

Malformed/unexpected response bodies (invalid JSON, or JSON that
doesn't match ClientServiceResponse's shape) are deliberately left
UNWRAPPED -- not caught and translated into ServiceUnavailableError.
That would mischaracterize a genuine contract-drift bug as routine,
retry-later unavailability. Letting it surface as an unhandled 500 is
more honest about what actually went wrong; a better-fitting error
type can be introduced later if this needs to be more specific.

Response schema fully verified against Client Service's real source
(app/api/v1/clients.py, app/api/schemas/client.py, site.py, contact.py,
address.py) -- not a reconstruction from the frozen design docs alone.
ClientServiceResponse/ClientSiteResponse/ClientContactResponse/
SiteAddressResponse below intentionally model a SUBSET of the real
response shapes -- only the fields Job Service actually reads
(id/name/status/sites/contacts; id/label/address; id/name/email/phone;
line1/line2/city/postcode/country). Pydantic v2's default
extra="ignore" means the real responses' additional fields (client_id,
tenant_id, is_primary, role, created_at, updated_at, client_type)
parse without error; they're omitted here because Job Service never
reads them, not because they don't exist on the wire.

status is deliberately typed as plain str, not an imported ClientStatus
enum -- confirmed correct against 01-domain-foundations.md §9's "Job
Service never imports another service's Python code."
"""

from __future__ import annotations

from uuid import UUID

import httpx
from pydantic import BaseModel

from app.exceptions.job import ClientNotFoundError, ServiceUnavailableError


class SiteAddressResponse(BaseModel):
    """Matches app/api/schemas/address.py's AddressResponse exactly
    (line1/line2/city/postcode/country) -- confirmed against real
    source, not inferred."""

    line1: str
    line2: str | None
    city: str
    postcode: str
    country: str | None


class ClientSiteResponse(BaseModel):
    id: UUID
    label: str
    address: SiteAddressResponse


class ClientContactResponse(BaseModel):
    id: UUID
    name: str
    email: str | None
    phone: str | None


class ClientServiceResponse(BaseModel):
    """Subset of GET /v1/clients/{client_id} consumed by Job Service."""

    id: UUID
    name: str
    status: str
    sites: list[ClientSiteResponse]
    contacts: list[ClientContactResponse]


class ClientServiceClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def get_client(
        self, client_id: UUID, access_token: str
    ) -> ClientServiceResponse:
        """Fetch a client by ID, forwarding the caller's own verified
        JWT unchanged. Raises ClientNotFoundError on 404,
        ServiceUnavailableError for anything else that isn't a clean
        200."""
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{self._base_url}/v1/clients/{client_id}"

        async with httpx.AsyncClient(
            timeout=self._timeout_seconds, transport=self._transport
        ) as client:
            response = await self._get_with_one_retry(client, url, headers)

        if response.status_code == 404:
            raise ClientNotFoundError(client_id)
        if response.status_code != 200:
            raise ServiceUnavailableError(
                f"Client Service returned unexpected status {response.status_code}."
            )

        return ClientServiceResponse.model_validate(response.json())

    async def _get_with_one_retry(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str]
    ) -> httpx.Response:
        """Exactly one retry, transport-level failures only -- never
        for a completed HTTP response, per Amendment 7."""
        try:
            return await client.get(url, headers=headers)
        except httpx.TransportError:
            try:
                return await client.get(url, headers=headers)
            except httpx.TransportError as exc:
                raise ServiceUnavailableError(
                    "Client Service could not be reached after one retry."
                ) from exc
