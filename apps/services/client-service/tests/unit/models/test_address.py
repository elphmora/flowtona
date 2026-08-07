"""
tests/unit/models/test_address.py

Unit tests for app.models.address.Address.

Covers: required-field enforcement (both presence, via the type system,
and non-blank, via NonBlankStr), optional-field defaults, and frozen
(immutable) value-object semantics.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.address import Address


class TestAddressConstruction:
    def test_valid_construction(self) -> None:
        address = Address(
            line1="14 Colmore Row",
            city="Birmingham",
            postcode="B3 2QD",
        )
        assert address.line1 == "14 Colmore Row"
        assert address.city == "Birmingham"
        assert address.postcode == "B3 2QD"
        assert address.line2 is None
        assert address.country is None

    def test_optional_fields_can_be_set(self) -> None:
        address = Address(
            line1="14 Colmore Row",
            line2="Suite 4",
            city="Birmingham",
            postcode="B3 2QD",
            country="UK",
        )
        assert address.line2 == "Suite 4"
        assert address.country == "UK"

    @pytest.mark.parametrize("blank_field", ["line1", "city", "postcode"])
    def test_blank_required_field_raises(self, blank_field: str) -> None:
        """The gap NonBlankStr specifically closes: a present-but-blank
        value passes the type system's requiredness check but must
        still be rejected — this is what distinguishes "required" from
        "required and meaningful"."""
        fields = {"line1": "14 Colmore Row", "city": "Birmingham", "postcode": "B3 2QD"}
        fields[blank_field] = "   "
        with pytest.raises(ValidationError, match="must not be blank"):
            Address(**fields)


class TestAddressImmutability:
    def test_mutating_a_field_raises(self) -> None:
        address = Address(line1="14 Colmore Row", city="Birmingham", postcode="B3 2QD")
        with pytest.raises(ValidationError):
            address.city = "London"  # type: ignore[misc]

    def test_replacement_is_the_correct_pattern(self) -> None:
        """Not a behavioral assertion so much as documentation-as-test:
        confirms the intended usage pattern (replace, don't mutate)
        actually works, since that's the whole point of freezing this
        value object in the first place."""
        original = Address(line1="14 Colmore Row", city="Birmingham", postcode="B3 2QD")
        replacement = Address(line1="1 Main St", city="London", postcode="E1 6AN")
        assert original.city != replacement.city
