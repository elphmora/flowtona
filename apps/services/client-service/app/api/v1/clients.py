"""
app/api/v1/clients.py

Routes for the `clients` resource (01-api-contract.md). Every route
requires clients:read (GET) or clients:write (POST/PATCH/DELETE) via
require_permission() — tenant_id for every service call comes only
from claims.tenant_id (the verified JWT claim), never from request
input (Platform Conventions §5).

No explicit exception handling anywhere below — ClientNotFoundError,
ClientArchivedError, ArchiveViaUpdateNotAllowedError, and
RequestValidationError (schema/query validation) all already flow
through app/api/errors.py's registered handlers into the correct RFC
9457 response. Routes only orchestrate: extract input, call the
service, shape the response.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import (
    get_client_service,
    get_contact_service,
    get_site_service,
)
from app.api.permission_dependency import require_permission
from app.api.schemas.client import (
    ClientCreateRequest,
    ClientListItem,
    ClientListResponse,
    ClientResponse,
    ClientUpdateRequest,
)
from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.models.client import Client
from app.models.enums import ClientStatus, ClientType
from app.security.token_verifier import AccessTokenClaims
from app.services.client_service import ClientService
from app.services.contact_service import ContactService
from app.services.site_service import SiteService

router = APIRouter(prefix="/v1/clients", tags=["clients"])

_MAX_LIMIT = 100


async def _build_client_response(
    client: Client,
    *,
    site_service: SiteService,
    contact_service: ContactService,
    tenant_id: UUID,
) -> ClientResponse:
    """Shared by POST/GET/PATCH — all three return the same full
    nested shape (Decision 6). Takes an already-fetched Client rather
    than a client_id, so POST/PATCH (which already have the object
    from create_client()/update_client()'s own return value) don't
    perform a redundant extra lookup — meaningless for the in-memory
    repository today, but a real cost (an avoidable query) once
    persistence moves beyond it. Only GET (which has no Client object
    yet) fetches first, then calls this."""
    sites = await site_service.list_sites(tenant_id=tenant_id, client_id=client.id)
    contacts = await contact_service.list_contacts(
        tenant_id=tenant_id, client_id=client.id
    )
    return ClientResponse.from_domain(client, sites=sites, contacts=contacts)


@router.post("", status_code=201)
async def create_client(
    body: ClientCreateRequest,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    client_service: Annotated[ClientService, Depends(get_client_service)],
    site_service: Annotated[SiteService, Depends(get_site_service)],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ClientResponse:
    client = await client_service.create_client(
        tenant_id=claims.tenant_id, name=body.name, client_type=body.client_type
    )
    return await _build_client_response(
        client,
        site_service=site_service,
        contact_service=contact_service,
        tenant_id=claims.tenant_id,
    )


@router.get("")
async def list_clients(
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_READ))],
    client_service: Annotated[ClientService, Depends(get_client_service)],
    site_service: Annotated[SiteService, Depends(get_site_service)],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
    name: str | None = None,
    status: ClientStatus | None = None,
    client_type: ClientType | None = None,
    limit: int = Query(default=20, ge=1),
    offset: int = Query(default=0, ge=0),
) -> ClientListResponse:
    """limit clamps silently to 100 when higher — not rejected. This
    is deliberately different from ge=1's behavior above: `0`/negative
    is a malformed request (422), but limit=500 is a well-formed
    request for more than this API is willing to return in one page —
    a different kind of problem, handled by giving the caller as much
    as is allowed rather than an error (01-api-contract.md Decision
    7)."""
    clamped_limit = min(limit, _MAX_LIMIT)

    page = await client_service.list_clients(
        tenant_id=claims.tenant_id,
        name=name,
        status=status,
        client_type=client_type,
        limit=clamped_limit,
        offset=offset,
    )

    items = []
    for client in page.items:
        sites = await site_service.list_sites(
            tenant_id=claims.tenant_id, client_id=client.id
        )
        contacts = await contact_service.list_contacts(
            tenant_id=claims.tenant_id, client_id=client.id
        )
        items.append(
            ClientListItem.from_domain(
                client, site_count=len(sites), contact_count=len(contacts)
            )
        )

    return ClientListResponse(
        items=items, total=page.total, limit=clamped_limit, offset=offset
    )


@router.get("/{client_id}")
async def get_client(
    client_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_READ))],
    client_service: Annotated[ClientService, Depends(get_client_service)],
    site_service: Annotated[SiteService, Depends(get_site_service)],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ClientResponse:
    client = await client_service.get_client(
        tenant_id=claims.tenant_id, client_id=client_id
    )
    return await _build_client_response(
        client,
        site_service=site_service,
        contact_service=contact_service,
        tenant_id=claims.tenant_id,
    )


@router.patch("/{client_id}")
async def update_client(
    client_id: UUID,
    body: ClientUpdateRequest,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    client_service: Annotated[ClientService, Depends(get_client_service)],
    site_service: Annotated[SiteService, Depends(get_site_service)],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ClientResponse:
    client = await client_service.update_client(
        tenant_id=claims.tenant_id,
        client_id=client_id,
        name=body.name,
        client_type=body.client_type,
        status=body.status,
    )
    return await _build_client_response(
        client,
        site_service=site_service,
        contact_service=contact_service,
        tenant_id=claims.tenant_id,
    )


@router.delete("/{client_id}", status_code=204)
async def archive_client(
    client_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    client_service: Annotated[ClientService, Depends(get_client_service)],
) -> Response:
    """Archives, per Decision 5 — does not hard-delete. Idempotent:
    archiving an already-archived client returns 204 again, not an
    error (enforced by ClientRepository.archive() itself; the metric's
    idempotency-awareness lives in ClientService.archive_client())."""
    await client_service.archive_client(tenant_id=claims.tenant_id, client_id=client_id)
    return Response(status_code=204)
