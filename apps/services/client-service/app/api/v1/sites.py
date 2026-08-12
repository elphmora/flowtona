"""
app/api/v1/sites.py

Routes for the `sites` subresource, nested under a client
(01-api-contract.md). Every route requires clients:read (GET) or
clients:write (POST/PATCH/DELETE) — sites don't have their own
permission scope, matching Platform Conventions §12's own boundary
(client-service owns exactly two permissions).

Unlike client DELETE (archives, idempotent), site DELETE is a genuine
hard delete — a second DELETE against the same site_id returns 404,
not 204.

No explicit exception handling — SiteNotFoundError, ClientNotFoundError,
ClientArchivedError, and RequestValidationError all already flow
through app/api/errors.py's registered handlers.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_site_service
from app.api.permission_dependency import require_permission
from app.api.schemas.site import SiteCreateRequest, SiteResponse, SiteUpdateRequest
from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.security.token_verifier import AccessTokenClaims
from app.services.site_service import SiteService

router = APIRouter(prefix="/v1/clients/{client_id}/sites", tags=["sites"])


@router.post("", status_code=201)
async def create_site(
    client_id: UUID,
    body: SiteCreateRequest,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    site_service: Annotated[SiteService, Depends(get_site_service)],
) -> SiteResponse:
    site = await site_service.create_site(
        tenant_id=claims.tenant_id,
        client_id=client_id,
        label=body.label,
        address=body.address.to_domain(),
        is_primary=body.is_primary,
    )
    return SiteResponse.from_domain(site)


@router.get("")
async def list_sites(
    client_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_READ))],
    site_service: Annotated[SiteService, Depends(get_site_service)],
) -> list[SiteResponse]:
    sites = await site_service.list_sites(
        tenant_id=claims.tenant_id, client_id=client_id
    )
    return [SiteResponse.from_domain(site) for site in sites]


@router.get("/{site_id}")
async def get_site(
    client_id: UUID,
    site_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_READ))],
    site_service: Annotated[SiteService, Depends(get_site_service)],
) -> SiteResponse:
    site = await site_service.get_site(
        tenant_id=claims.tenant_id, client_id=client_id, site_id=site_id
    )
    return SiteResponse.from_domain(site)


@router.patch("/{site_id}")
async def update_site(
    client_id: UUID,
    site_id: UUID,
    body: SiteUpdateRequest,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    site_service: Annotated[SiteService, Depends(get_site_service)],
) -> SiteResponse:
    site = await site_service.update_site(
        tenant_id=claims.tenant_id,
        client_id=client_id,
        site_id=site_id,
        label=body.label,
        address=body.address.to_domain() if body.address is not None else None,
        is_primary=body.is_primary,
    )
    return SiteResponse.from_domain(site)


@router.delete("/{site_id}", status_code=204)
async def delete_site(
    client_id: UUID,
    site_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    site_service: Annotated[SiteService, Depends(get_site_service)],
) -> Response:
    """Hard delete, per Decision 9 — NOT idempotent the way client
    archive is. A second DELETE against an already-deleted site_id
    correctly returns 404, not 204."""
    await site_service.delete_site(
        tenant_id=claims.tenant_id, client_id=client_id, site_id=site_id
    )
    return Response(status_code=204)
