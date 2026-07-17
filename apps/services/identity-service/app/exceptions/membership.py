"""
app/exceptions/membership.py

Domain exceptions for membership-related business rules (Decision 8).
"""

from app.exceptions.base import DomainError


class AlreadyAMemberError(DomainError):
    code = "already_a_member"
    status_code = 409
    title = "Already a member"

    def __init__(self) -> None:
        super().__init__("This user is already a member of this tenant.")
