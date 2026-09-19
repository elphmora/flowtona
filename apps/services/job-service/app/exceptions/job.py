"""
app/exceptions/job.py

Seven exceptions. ClientNotFoundError/ServiceUnavailableError are owned
by ClientServiceClient's own error translation (built earlier).
ClientArchivedError/SiteNotFoundError/ContactNotFoundError are owned
by JobService.validate_client_reference() -- per 01-create-job.md's
sequence diagram, these come from inspecting the already-fetched
client's status/sites/contacts locally, not a further network call.

JobNotFoundError and VisitNotFoundError land here for the Query
Operations checkpoint -- genuinely distinct codes (job_not_found vs.
visit_not_found), confirmed against 03-api-contract.md's own Future
Documentation section, which lists both separately among the
contract's error codes rather than collapsing them into one.

JobNotFoundError's detail message is deliberately generic -- it never
distinguishes "doesn't exist" from "belongs to a different tenant"
(03-api-contract.md: "identical response whether not found or belongs
to a different tenant"), matching ClientNotFoundError's own established
wording pattern above.
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


class JobNotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Job not found"
    code = "job_not_found"

    def __init__(self, job_id: UUID) -> None:
        super().__init__(detail=f"No job exists with ID {job_id}.")


class VisitNotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    title = "Visit not found"
    code = "visit_not_found"

    def __init__(self, visit_id: UUID) -> None:
        super().__init__(detail=f"No visit exists with ID {visit_id} under this job.")
