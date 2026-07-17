"""
app/exceptions/invitation.py

Domain exceptions for invitation-related business rules (Decision 8).

Three types, mirroring EmailVerification's split with one addition:
- InvitationInvalidError: generic — not found, or already accepted.
  No caller needs to distinguish those; both resolve identically
  (nothing to do, the invite is dead).
- InvitationExpiredError: specific, matching 01-api-contract.md's
  explicit 410 for expired invites.
- InvitationEmailMismatchError: specific to invitations, no
  EmailVerification equivalent — matches 01-api-contract.md's 409 for
  when an authenticated existing user's email doesn't match the
  invite's target email (Flow 7). Raised by AuthService, not
  InvitationService, since only AuthService has both the User and the
  Invitation in hand to compare.
"""

from app.exceptions.base import DomainError


class InvitationInvalidError(DomainError):
    code = "invalid_invitation"
    status_code = 400
    title = "Invalid invitation"

    def __init__(self) -> None:
        super().__init__("This invitation is invalid or has already been used.")


class InvitationExpiredError(DomainError):
    code = "invitation_expired"
    status_code = 410
    title = "Invitation expired"

    def __init__(self) -> None:
        super().__init__("This invitation has expired.")


class InvitationEmailMismatchError(DomainError):
    code = "invitation_email_mismatch"
    status_code = 409
    title = "Invitation email mismatch"

    def __init__(self) -> None:
        super().__init__(
            "This invitation was sent to a different email address than your account's."
        )
