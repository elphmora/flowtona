"""
app/exceptions/auth.py

Domain exceptions for the JWT verification / authorization boundary —
not owned by any single entity service, since these represent
request-authentication outcomes rather than one entity's business
rules. Same category as identity-service's own app/exceptions/auth.py
(e.g. InvalidCredentialsError), just for the consumer side rather than
the issuer side.
"""

from app.exceptions.base import DomainError


class InvalidAccessTokenError(DomainError):
    """The supplied access token cannot be accepted.

    Covers missing/malformed credentials, failed cryptographic or
    standard-claim verification, non-access token types, and required
    application claims that are missing or malformed.
    """

    code = "invalid_access_token"
    status_code = 401
    title = "Invalid access token"

    def __init__(self) -> None:
        super().__init__("The access token is missing, invalid, or expired.")


class InsufficientPermissionError(DomainError):
    """The token is valid but lacks the permission required by the route."""

    code = "insufficient_permission"
    status_code = 403
    title = "Insufficient permission"

    def __init__(self) -> None:
        super().__init__("You do not have permission to perform this action.")
