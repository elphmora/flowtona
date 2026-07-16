"""
app/exceptions/user.py

Domain exceptions for user-related business rules (Decision 8).
"""

from app.exceptions.base import DomainError


class EmailAlreadyRegisteredError(DomainError):
    code = "email_already_registered"
    status_code = 409
    title = "Email already registered"

    def __init__(self, *, email: str) -> None:
        # Echoing the email back is fine here (unlike repository-layer
        # exceptions, which omit sensitive values on principle) — the
        # client submitting a signup request already knows the email
        # they just typed; this isn't disclosing anything new to them.
        super().__init__(f"An account is already registered for {email}.")
