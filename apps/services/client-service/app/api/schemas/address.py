"""
app/api/schemas/address.py

Response shape for the Address value object, embedded in Site
responses, plus the request-side counterpart embedded in Site create/
update requests.
"""

from pydantic import BaseModel, ConfigDict

from app.models.address import Address
from app.models.types import NonBlankStr


class AddressResponse(BaseModel):
    line1: str
    line2: str | None
    city: str
    postcode: str
    country: str | None


class AddressRequest(BaseModel):
    """Reuses NonBlankStr directly from the domain layer for
    line1/city/postcode — same reasoning as ClientCreateRequest.name:
    one definition of "non-blank," shared by the HTTP boundary and the
    domain model, not two rules that could drift apart."""

    model_config = ConfigDict(extra="forbid")

    line1: NonBlankStr
    line2: str | None = None
    city: NonBlankStr
    postcode: NonBlankStr
    country: str | None = None

    def to_domain(self) -> Address:
        return Address(
            line1=self.line1,
            line2=self.line2,
            city=self.city,
            postcode=self.postcode,
            country=self.country,
        )
