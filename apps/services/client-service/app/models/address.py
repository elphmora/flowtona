"""
app/models/address.py

Address value object, embedded on Site.

Not a standalone entity — no id, no tenant_id, no independent lifecycle
or repository. Frozen (immutable) — a value object is replaced, not
mutated in place: `site.address = Address(...)`, never
`site.address.city = "..."`. Site itself stays mutable; only the value
object it holds is frozen.

line1/city/postcode are required and non-blank (NonBlankStr) — an
Address without them isn't a meaningful domain object, regardless of
which path constructed it. line2/country stay optional. The decision
to leave postcode format generic rather than UK-specific (Decision 8)
is the one thing that does stay at the API schema layer — format/regex
validation is an HTTP-input-cleaning concern, distinct from the
structural "can this object exist at all" question NonBlankStr answers.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.types import NonBlankStr


class Address(BaseModel):
    model_config = ConfigDict(frozen=True)

    line1: NonBlankStr
    line2: str | None = None
    city: NonBlankStr
    postcode: NonBlankStr
    country: str | None = None
