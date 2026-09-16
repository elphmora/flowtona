"""
app/exceptions/auth.py

Two exceptions for the JWT/permission layer. Split from
app/exceptions/job.py -- these are cross-cutting security concerns,
not Job-domain concerns, matching client-service's own file split.

WWW-Authenticate on 401 -- previously flagged here as unconfirmed --
is now implemented, generically, in app/api/errors.py's
handle_domain_error (based on exc.status_code == 401, not specific to
this class by name), confirmed against client-service's own real
errors.py.
"""

from __future__ import annotations

from fastapi import status

from app.exceptions.base import DomainError


class InvalidAccessTokenError(DomainError):
    status_code = status.HTTP_401_UNAUTHORIZED
    title = "Invalid access token"
    code = "invalid_access_token"

    def __init__(self) -> None:
        super().__init__(detail="The access token is missing, malformed, or invalid.")


class InsufficientPermissionError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN
    title = "Insufficient permission"
    code = "insufficient_permission"

    def __init__(self) -> None:
        super().__init__(
            detail="The access token does not carry the required permission."
        )
