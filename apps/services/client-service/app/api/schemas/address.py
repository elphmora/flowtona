"""
app/api/schemas/address.py

Response shape for the Address value object, embedded in Site
responses. No request/create schema here — Address is never created
independently of a Site (app/models/address.py: "Not a standalone
entity — no id, no tenant_id, no independent lifecycle or
repository").
"""

from pydantic import BaseModel


class AddressResponse(BaseModel):
    line1: str
    line2: str | None
    city: str
    postcode: str
    country: str | None
