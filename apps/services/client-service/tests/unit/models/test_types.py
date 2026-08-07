"""
tests/unit/models/test_types.py

Unit tests for app.models.types — NonBlankStr and utc_now().

These are tested directly, not just indirectly through the models that
use them, so a future change to NonBlankStr's behavior (e.g. loosening
or tightening the blank-check) has one clear place to fail, rather than
only surfacing as unexplained failures scattered across every model
that imports it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, ValidationError

from app.models.types import NonBlankStr, utc_now


class _Holder(BaseModel):
    """Minimal model for exercising NonBlankStr in isolation, without
    coupling this test to any real domain model's other fields."""

    value: NonBlankStr


class TestNonBlankStr:
    def test_accepts_non_blank_value(self) -> None:
        holder = _Holder(value="Birmingham")
        assert holder.value == "Birmingham"

    @pytest.mark.parametrize("blank_value", ["", "   ", "\t", "\n", "  \t\n  "])
    def test_rejects_blank_or_whitespace_only(self, blank_value: str) -> None:
        with pytest.raises(ValidationError, match="must not be blank"):
            _Holder(value=blank_value)

    def test_does_not_strip_valid_surrounding_whitespace(self) -> None:
        """NonBlankStr only rejects blank; it does not trim. Trimming is
        an API-schema-layer concern (Decision 8), not this type's job —
        this test pins that boundary down explicitly."""
        holder = _Holder(value="  Birmingham  ")
        assert holder.value == "  Birmingham  "


class TestUtcNow:
    def test_returns_timezone_aware_utc_datetime(self) -> None:
        """The one thing worth guarding here: a naive datetime slipping
        in by accident is a real, common Python footgun (silent
        comparison/serialization bugs later) — this is our logic
        (choosing timezone.utc), not the stdlib's."""
        result = utc_now()
        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        assert result.tzinfo.utcoffset(result) == timezone.utc.utcoffset(None)
