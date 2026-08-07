"""
tests/unit/models/test_enums.py

Unit tests for app.models.enums — ClientType and ClientStatus.

Minimal on purpose: str-Enum membership is largely exercised already
via the model tests (constructing a Client/etc. with each value). This
file covers what those don't: the enum's own value set and str
behavior, independent of any model that uses it.
"""

from __future__ import annotations

from app.models.enums import ClientStatus, ClientType


class TestClientType:
    def test_expected_members(self) -> None:
        assert {member.value for member in ClientType} == {"residential", "commercial"}

    def test_is_a_str_subclass(self) -> None:
        """ClientType(str, Enum) — confirms it serializes/compares as a
        plain string, which matters for JSON responses and repository
        equality checks alike."""
        assert ClientType.COMMERCIAL == "commercial"
        assert isinstance(ClientType.COMMERCIAL, str)


class TestClientStatus:
    def test_expected_members(self) -> None:
        assert {member.value for member in ClientStatus} == {
            "active",
            "inactive",
            "archived",
        }

    def test_is_a_str_subclass(self) -> None:
        assert ClientStatus.ARCHIVED == "archived"
        assert isinstance(ClientStatus.ARCHIVED, str)
