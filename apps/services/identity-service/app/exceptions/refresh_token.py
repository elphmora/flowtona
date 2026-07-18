"""
app/exceptions/refresh_token.py

Domain exceptions for refresh-token business rules (Decision 8). No
structured metadata (e.g. an "action": "reauthenticate" hint) baked in
here — that's route-layer/API-contract concern, not the exception's.
"""

from app.exceptions.base import DomainError


class InvalidRefreshTokenError(DomainError):
    code = "invalid_refresh_token"
    status_code = 401
    title = "Invalid refresh token"

    def __init__(self) -> None:
        super().__init__("This refresh token is invalid, revoked, or expired.")


class RefreshTokenReuseDetectedError(DomainError):
    code = "token_reuse_detected"
    status_code = 401
    title = "Refresh token reuse detected"

    def __init__(self) -> None:
        super().__init__(
            "The session associated with this token has been signed out for safety."
        )
