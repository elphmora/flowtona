"""
app/exceptions/job.py

Five exceptions. ClientNotFoundError/ServiceUnavailableError are owned
by ClientServiceClient's own error translation (built earlier).
ClientArchivedError/SiteNotFoundError/ContactNotFoundError are owned
by JobService.validate_client_reference() -- per 01-create-job.md's
sequence diagram, these come from inspecting the already-fetched
client's status/sites/contacts locally, not a further network call.

JobNotFoundError still waits for the GET-by-ID checkpoint.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import status

from app.exceptions.base import DomainError


class ClientNotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Client not found"
    code = "client_not_found"

    def __init__(self, client_id: UUID) -> None:
        super().__init__(detail=f"No client exists with ID {client_id}.")


class ServiceUnavailableError(DomainError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    title = "Client Service unavailable"
    code = "client_service_unavailable"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail=detail or "Client Service could not be reached.")


class ClientArchivedError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    title = "Client is archived"
    code = "client_archived"

    def __init__(self, client_id: UUID) -> None:
        super().__init__(
            detail=f"Client {client_id} is archived and cannot be referenced by a new Job."
        )


class SiteNotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Site not found"
    code = "site_not_found"

    def __init__(self, site_id: UUID) -> None:
        super().__init__(detail=f"No site exists with ID {site_id} under this client.")


class ContactNotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Contact not found"
    code = "contact_not_found"

    def __init__(self, contact_id: UUID) -> None:
        super().__init__(
            detail=f"No contact exists with ID {contact_id} under this client."
        )
