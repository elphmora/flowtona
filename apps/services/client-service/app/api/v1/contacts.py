"""
app/api/v1/contacts.py

Routes for the `contacts` subresource, nested under a client
(01-api-contract.md). Every route requires clients:read (GET) or
clients:write (POST/PATCH/DELETE) — same permission scope as sites,
contacts don't have their own.

update_contact is where this route file does real work beyond
orchestration: ContactService.update_contact()'s role/email/phone/
site_id parameters are UNSET-aware (see contact_service.py's module
docstring) — this route reads body.model_fields_set to determine
which fields were actually present in the request (vs. using their
default), and passes UNSET for anything omitted, or the real value
(including None) for anything explicitly present. This is the exact
resolution point contact_service.py's docstring describes: "which
fields were actually present in the request is a fact the route/
schema layer determines... this service only receives the already-
resolved UNSET/None/value."

The `?site_id=` list filter deliberately does NOT validate site
ownership — a well-formed but non-matching site_id returns 200 [],
per the contract; ContactService.list_contacts() already implements
this correctly by not calling SiteService.get_site() for the filter
case, so this route just passes the query parameter through unchanged.

No explicit exception handling — ContactNotFoundError,
ContactRequiresEmailOrPhoneError, SiteNotFoundError, ClientNotFoundError,
ClientArchivedError, and RequestValidationError all already flow
through app/api/errors.py's registered handlers.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_contact_service
from app.api.permission_dependency import require_permission
from app.api.schemas.contact import (
    ContactCreateRequest,
    ContactResponse,
    ContactUpdateRequest,
)
from app.constants.permissions import CLIENTS_READ, CLIENTS_WRITE
from app.security.token_verifier import AccessTokenClaims
from app.services.contact_service import UNSET, ContactService

router = APIRouter(prefix="/v1/clients/{client_id}/contacts", tags=["contacts"])


@router.post("", status_code=201)
async def create_contact(
    client_id: UUID,
    body: ContactCreateRequest,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ContactResponse:
    contact = await contact_service.create_contact(
        tenant_id=claims.tenant_id,
        client_id=client_id,
        site_id=body.site_id,
        name=body.name,
        role=body.role,
        email=body.email,
        phone=body.phone,
        is_primary=body.is_primary,
    )
    return ContactResponse.from_domain(contact)


@router.get("")
async def list_contacts(
    client_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_READ))],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
    site_id: UUID | None = None,
) -> list[ContactResponse]:
    contacts = await contact_service.list_contacts(
        tenant_id=claims.tenant_id, client_id=client_id, site_id=site_id
    )
    return [ContactResponse.from_domain(contact) for contact in contacts]


@router.get("/{contact_id}")
async def get_contact(
    client_id: UUID,
    contact_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_READ))],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ContactResponse:
    contact = await contact_service.get_contact(
        tenant_id=claims.tenant_id, client_id=client_id, contact_id=contact_id
    )
    return ContactResponse.from_domain(contact)


@router.patch("/{contact_id}")
async def update_contact(
    client_id: UUID,
    contact_id: UUID,
    body: ContactUpdateRequest,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> ContactResponse:
    fields_set = body.model_fields_set
    contact = await contact_service.update_contact(
        tenant_id=claims.tenant_id,
        client_id=client_id,
        contact_id=contact_id,
        name=body.name,
        role=body.role if "role" in fields_set else UNSET,
        email=body.email if "email" in fields_set else UNSET,
        phone=body.phone if "phone" in fields_set else UNSET,
        site_id=body.site_id if "site_id" in fields_set else UNSET,
        is_primary=body.is_primary,
    )
    return ContactResponse.from_domain(contact)


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    client_id: UUID,
    contact_id: UUID,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(CLIENTS_WRITE))],
    contact_service: Annotated[ContactService, Depends(get_contact_service)],
) -> Response:
    await contact_service.delete_contact(
        tenant_id=claims.tenant_id, client_id=client_id, contact_id=contact_id
    )
    return Response(status_code=204)
