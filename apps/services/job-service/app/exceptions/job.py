"""
app/exceptions/job.py

Two exceptions only -- exactly what ClientServiceClient's own error
translation needs (404 -> ClientNotFoundError; unreachable, timed-out-
after-retry, or any other non-200/404 status -> ServiceUnavailableError).

ClientArchivedError, SiteNotFoundError, and ContactNotFoundError are
deliberately NOT here yet. Per 01-create-job.md's sequence diagram,
those come from validate_client_reference() -- a JobService method
that inspects the ALREADY-fetched client's status/sites/contacts
locally, not a further ClientServiceClient responsibility. They land
alongside JobService.create_job() in the next checkpoint.
JobNotFoundError likewise waits for the route/service wiring.
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
