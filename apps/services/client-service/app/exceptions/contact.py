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
