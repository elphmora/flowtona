"""
tests/unit/api/test_auth_dependency.py
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.api.auth_dependency import get_current_claims
from app.exceptions.auth import InvalidAccessTokenError


class _FakeTokenVerifier:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def verify(self, raw_token: str) -> str:
        self.calls.append(raw_token)
        return "fake-claims"


async def test_get_current_claims_raises_when_credentials_missing() -> None:
    fake_verifier: Any = _FakeTokenVerifier()
    with pytest.raises(InvalidAccessTokenError):
        await get_current_claims(credentials=None, token_verifier=fake_verifier)


async def test_get_current_claims_calls_verifier_with_exact_raw_token() -> None:
    fake_verifier: Any = _FakeTokenVerifier()
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="the-raw-token"
    )

    result = await get_current_claims(
        credentials=credentials, token_verifier=fake_verifier
    )

    assert fake_verifier.calls == ["the-raw-token"]
    assert result == "fake-claims"
