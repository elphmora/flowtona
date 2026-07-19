"""
app/exceptions/auth.py

Domain exceptions owned by AuthService itself — not any single entity
service, since these represent orchestration-level outcomes (bad
credentials, no accessible tenant) rather than one aggregate's own
business rules.
"""

from app.exceptions.base import DomainError


class InvalidCredentialsError(DomainError):
    """Deliberately identical whether the email doesn't exist or the
    password is wrong — avoids user enumeration via the login
    endpoint's response."""

    code = "invalid_credentials"
    status_code = 401
    title = "Invalid credentials"

    def __init__(self) -> None:
        super().__init__("The email or password is incorrect.")


class NoActiveMembershipError(DomainError):
    """The credentials are valid, but the user has zero ACTIVE
    memberships — distinct from InvalidCredentialsError, since the
    identity itself was confirmed; there's simply no tenant this
    account can currently access (partial signup, membership removal,
    tenant deletion, or administrative suspension). 403, not 401 — the
    identity check passed, there's no authorization path forward."""

    code = "no_active_membership"
    status_code = 403
    title = "No active membership"

    def __init__(self) -> None:
        super().__init__(
            "Your account is not currently associated with an accessible business."
        )
