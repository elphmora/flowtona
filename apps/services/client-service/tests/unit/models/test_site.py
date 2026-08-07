"""
tests/unit/models/test_site.py

Unit tests for app.models.site.Site.

Note: is_primary auto-promotion/demotion (first-created auto-primary,
explicit-set demotes the previous holder — Decision 4) is deliberately
NOT tested here. That's a multi-record invariant enforced by
SiteService, which doesn't exist yet — this file tests only what the
Site model itself is responsible for, per its own docstring.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.address import Address
from app.models.site import Site


def _address() -> Address:
    return Address(line1="14 Colmore Row", city="Birmingham", postcode="B3 2QD")


class TestSiteConstruction:
    def test_valid_construction_defaults(self) -> None:
        client_id = uuid4()
        tenant_id = uuid4()
        site = Site(
            client_id=client_id,
            tenant_id=tenant_id,
            label="Main Warehouse",
            address=_address(),
        )
        assert site.client_id == client_id
        assert site.tenant_id == tenant_id
        assert site.label == "Main Warehouse"
        # is_primary defaults false at the model level — auto-primary-on-
        # first-create is SiteService's job, not this model's (see module
        # docstring above and Site's own class docstring).
        assert site.is_primary is False

    def test_blank_label_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be blank"):
            Site(client_id=uuid4(), tenant_id=uuid4(), label="   ", address=_address())

    def test_holds_a_frozen_address(self) -> None:
        """Site itself stays mutable; only the Address it holds is
        frozen — this test confirms that boundary, since it's easy to
        assume freezing Address transitively freezes Site too."""
        site = Site(client_id=uuid4(), tenant_id=uuid4(), label="A", address=_address())
        site.label = "Renamed"  # Site is not frozen — this must succeed.
        assert site.label == "Renamed"
        with pytest.raises(ValidationError):
            site.address.city = "London"  # type: ignore[misc]
