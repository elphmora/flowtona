"""
app/exceptions/contact.py

Domain exceptions raised by ContactService — 01-api-contract.md's
error catalog for the Contact subresource.
"""

from app.exceptions.base import DomainError


class ContactNotFoundError(DomainError):
    code = "contact_not_found"
    status_code = 404
    title = "Contact not found"

    def __init__(self) -> None:
        super().__init__("No contact exists with this ID under this client.")


class ContactRequiresEmailOrPhoneError(DomainError):
    """Decision 8's invariant, enforced at the MERGED-state level for
    updates — not solely by Pydantic on the request body alone. A
    PATCH clearing email while the existing contact has no phone (or
    vice versa) must be rejected using the contact's resulting state
    after the update is applied, which the request body alone cannot
    determine (it doesn't know what the existing contact currently
    has in the field that isn't being changed)."""

    code = "contact_requires_email_or_phone"
    status_code = 422
    title = "Contact requires email or phone"

    def __init__(self) -> None:
        super().__init__(
            "A contact must have at least one of email or phone — this "
            "update would leave both empty."
        )
