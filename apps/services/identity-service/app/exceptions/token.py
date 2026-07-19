"""
app/exceptions/token.py

Domain exceptions for JWT verification failures (Decision 8). Four
types, not two — expired vs. generically-invalid is split for both
token types, matching the pattern already established for
EmailVerificationService/InvitationService (VerificationTokenExpiredError
vs. VerificationTokenInvalidError; InvitationExpiredError vs.
InvitationInvalidError). Same reasoning applies here: the client's
correct response differs — an expired access token means "use your
refresh token"; an invalid one means "something is fundamentally
wrong, re-authenticate from scratch."
"""

from app.exceptions.base import DomainError


class InvalidAccessTokenError(DomainError):
    code = "invalid_access_token"
    status_code = 401
    title = "Invalid access token"

    def __init__(self) -> None:
        super().__init__("This access token is invalid or malformed.")


class ExpiredAccessTokenError(DomainError):
    code = "access_token_expired"
    status_code = 401
    title = "Access token expired"

    def __init__(self) -> None:
        super().__init__(
            "This access token has expired. Use your refresh token to obtain a new one."
        )


class InvalidPreauthTokenError(DomainError):
    code = "invalid_preauth_token"
    status_code = 401
    title = "Invalid pre-authentication token"

    def __init__(self) -> None:
        super().__init__("This tenant-selection token is invalid or malformed.")


class ExpiredPreauthTokenError(DomainError):
    code = "preauth_token_expired"
    status_code = 401
    title = "Pre-authentication token expired"

    def __init__(self) -> None:
        super().__init__(
            "This tenant-selection token has expired. Please sign in again."
        )
