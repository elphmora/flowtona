"""
app/exceptions/email_verification.py

Domain exceptions for email-verification business rules (Decision 8).

Two types, not one generic "invalid token" — matching 01-api-contract.md's
already-published distinction: POST /v1/auth/email/verify specifically
calls out 410 for an expired token (with explicit guidance to call
resend), separate from the generic invalid case. This isn't an
enumeration concern the way login's "same error for wrong email or
wrong password" is — a verification token is mailed directly to the
person controlling that mailbox, so telling them "this expired,
request a new one" vs. "this link isn't valid" carries no meaningful
attack surface, and the UX benefit (a specific "resend" prompt) is real.

Deliberately NOT distinguishing "token never existed" from "already
consumed/revoked" — no caller needs to tell those apart, and both
resolve identically (request a new one via resend).
"""

from app.exceptions.base import DomainError


class VerificationTokenInvalidError(DomainError):
    code = "invalid_verification_token"
    status_code = 400
    title = "Invalid verification token"

    def __init__(self) -> None:
        super().__init__("This verification link is invalid or has already been used.")


class VerificationTokenExpiredError(DomainError):
    code = "verification_token_expired"
    status_code = 410
    title = "Verification token expired"

    def __init__(self) -> None:
        super().__init__("This verification link has expired. Request a new one.")
