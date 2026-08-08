"""
app/exceptions/client.py

Domain exceptions raised by ClientService — 01-api-contract.md's error
catalog for the Client resource and Decision 5's archived-immutability
rule.
"""

from app.exceptions.base import DomainError


class ClientNotFoundError(DomainError):
    code = "client_not_found"
    status_code = 404
    title = "Client not found"

    def __init__(self) -> None:
        super().__init__("No client exists with this ID in your tenant.")


class ClientArchivedError(DomainError):
    """Decision 5: archived is fully immutable in Phase 1 — any write
    against an archived client, or anything beneath it, is rejected."""

    code = "client_archived"
    status_code = 409
    title = "Client archived"

    def __init__(self) -> None:
        super().__init__("This client is archived and cannot be modified.")


class ArchiveViaUpdateNotAllowedError(DomainError):
    """update_client() rejects status=ARCHIVED outright — archiving is
    a dedicated, idempotent lifecycle transition (Decision 5), not a
    generic field edit. Enforced in the service layer, not only at a
    future API schema, so this rule holds regardless of caller (CLI,
    migration, background job, admin script — not just HTTP).

    409, not 422: the request is syntactically valid (well-formed
    field, valid enum value) — the problem is that this operation
    conflicts with how this resource's state is allowed to change,
    which is the same shape of problem ClientArchivedError already
    represents at 409, not a malformed-input problem. Not yet specified
    in 01-api-contract.md (this exception didn't exist when that
    document was written) — revisit if the contract is updated to say
    otherwise."""

    code = "archive_via_update_not_allowed"
    status_code = 409
    title = "Cannot archive via update"

    def __init__(self) -> None:
        super().__init__(
            "Archiving a client must be done via the archive operation, not update()."
        )
