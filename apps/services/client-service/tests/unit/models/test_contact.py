"""
tests/unit/models/test_contact.py

Unit tests for app.models.contact.Contact.

Note: is_primary auto-promotion/demotion is deliberately NOT tested
here, same reasoning as test_site.py — that's ContactService's job,
not this model's.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.contact import Contact


class TestContactConstruction:
    def test_valid_construction_with_email_only(self) -> None:
        contact = Contact(
            client_id=uuid4(),
            tenant_id=uuid4(),
            name="Priya Shah",
            email="priya@example.com",
        )
        assert contact.email == "priya@example.com"
        assert contact.phone is None
        assert contact.site_id is None
        assert contact.is_primary is False

    def test_valid_construction_with_phone_only(self) -> None:
        contact = Contact(
            client_id=uuid4(),
            tenant_id=uuid4(),
            name="Priya Shah",
            phone="+44 121 000 0000",
        )
        assert contact.phone == "+44 121 000 0000"
        assert contact.email is None

    def test_valid_construction_with_both_email_and_phone(self) -> None:
        contact = Contact(
            client_id=uuid4(),
            tenant_id=uuid4(),
            name="Priya Shah",
            email="priya@example.com",
            phone="+44 121 000 0000",
        )
        assert contact.email == "priya@example.com"
        assert contact.phone == "+44 121 000 0000"

    def test_neither_email_nor_phone_raises(self) -> None:
        with pytest.raises(ValidationError, match="at least one of email or phone"):
            Contact(client_id=uuid4(), tenant_id=uuid4(), name="No Contact Info")

    def test_blank_name_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be blank"):
            Contact(
                client_id=uuid4(),
                tenant_id=uuid4(),
                name="   ",
                phone="+44 121 000 0000",
            )

    def test_malformed_email_raises(self) -> None:
        """Confirms EmailStr's format enforcement is actually active —
        this is the one piece of format validation deliberately kept at
        the domain layer (see Contact's class docstring / the earlier
        discussion on why EmailStr differs from pure HTTP formatting)."""
        with pytest.raises(ValidationError):
            Contact(
                client_id=uuid4(),
                tenant_id=uuid4(),
                name="Priya Shah",
                email="not-an-email",
            )
