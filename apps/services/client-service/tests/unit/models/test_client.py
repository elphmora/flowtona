"""
tests/unit/models/test_client.py

Unit tests for app.models.client.Client.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.client import Client
from app.models.enums import ClientStatus, ClientType


class TestClientConstruction:
    def test_valid_construction_defaults(self) -> None:
        tenant_id = uuid4()
        client = Client(
            tenant_id=tenant_id,
            name="Birmingham Plumbing Co.",
            client_type=ClientType.COMMERCIAL,
        )
        assert client.tenant_id == tenant_id
        assert client.name == "Birmingham Plumbing Co."
        assert client.client_type == ClientType.COMMERCIAL
        # Decision 5: status defaults to active on construction.
        assert client.status == ClientStatus.ACTIVE
        assert client.id is not None

    def test_blank_name_raises(self) -> None:
        with pytest.raises(ValidationError, match="must not be blank"):
            Client(tenant_id=uuid4(), name="   ", client_type=ClientType.COMMERCIAL)

    def test_invalid_client_type_raises(self) -> None:
        """Confirms client_type is genuinely constrained to the
        ClientType enum, not silently accepting any string — worth
        one check that the enum boundary is actually enforced, without
        parametrizing over every valid member (that would just be
        re-testing Python's own Enum pass-through)."""
        with pytest.raises(ValidationError):
            Client(tenant_id=uuid4(), name="A", client_type="not_a_real_type")  # type: ignore[arg-type]


class TestClientAssignment:
    """validate_assignment=True means Client's validators
    run on attribute assignment, not just construction — these tests
    confirm that's actually true, not assumed from the config flag."""

    def test_assigning_blank_name_raises(self) -> None:
        client = Client(
            tenant_id=uuid4(), name="Valid Co.", client_type=ClientType.COMMERCIAL
        )
        with pytest.raises(ValidationError, match="must not be blank"):
            client.name = "   "
