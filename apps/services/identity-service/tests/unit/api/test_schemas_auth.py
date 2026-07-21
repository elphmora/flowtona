"""tests/unit/api/test_schemas_auth.py

Tests for app/api/schemas/auth.py's validation behavior and the
login discriminated union specifically.
"""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.api.schemas.auth import (
    AuthenticatedSessionResponse,
    LoginRequest,
    LoginResponseBody,
    SelectTenantRequest,
    SignupRequest,
    TenantSelectionRequiredResponse,
)


class TestSignupRequest:
    def test_accepts_valid_input(self):
        request = SignupRequest(
            email="dana@example.com",
            password="hunter22",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        assert request.email == "dana@example.com"

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            SignupRequest(
                email="not-an-email",
                password="hunter22",
                display_name="Dana",
                tenant_label="Dana's Plumbing",
            )

    def test_rejects_too_short_password(self):
        with pytest.raises(ValidationError):
            SignupRequest(
                email="dana@example.com",
                password="short",
                display_name="Dana",
                tenant_label="Dana's Plumbing",
            )

    def test_rejects_too_long_password(self):
        with pytest.raises(ValidationError):
            SignupRequest(
                email="dana@example.com",
                password="x" * 257,
                display_name="Dana",
                tenant_label="Dana's Plumbing",
            )

    def test_rejects_empty_display_name(self):
        with pytest.raises(ValidationError):
            SignupRequest(
                email="dana@example.com",
                password="hunter22",
                display_name="",
                tenant_label="Dana's Plumbing",
            )

    def test_rejects_whitespace_only_password(self):
        """The password is rejected, but NOT silently mutated for a
        legitimate password that merely contains whitespace — see
        _reject_whitespace_only's docstring in schemas/auth.py."""
        with pytest.raises(ValidationError):
            SignupRequest(
                email="dana@example.com",
                password="        ",
                display_name="Dana",
                tenant_label="Dana's Plumbing",
            )

    def test_whitespace_within_password_is_preserved_not_stripped(self):
        """A password that legitimately contains whitespace (not
        ENTIRELY whitespace) must reach AuthService completely
        unchanged — this is the key behavioral difference from a naive
        strip_whitespace=True constraint, which would have silently
        rewritten this value before it ever reaches hashing."""
        request = SignupRequest(
            email="dana@example.com",
            password="  correct horse battery staple  ",
            display_name="Dana",
            tenant_label="Dana's Plumbing",
        )
        assert request.password == "  correct horse battery staple  "


class TestLoginRequest:
    def test_accepts_valid_input(self):
        request = LoginRequest(email="dana@example.com", password="hunter2")
        assert request.email == "dana@example.com"

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="not-an-email", password="hunter2")

    def test_rejects_empty_password(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="dana@example.com", password="")

    def test_rejects_too_long_password(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="dana@example.com", password="x" * 257)

    def test_rejects_whitespace_only_password(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="dana@example.com", password="        ")


class TestSelectTenantRequest:
    def test_accepts_valid_input(self):
        request = SelectTenantRequest(
            preauth_token="some-token",
            tenant_id="11111111-1111-1111-1111-111111111111",
        )
        assert request.preauth_token == "some-token"

    def test_rejects_empty_preauth_token(self):
        with pytest.raises(ValidationError):
            SelectTenantRequest(
                preauth_token="", tenant_id="11111111-1111-1111-1111-111111111111"
            )

    def test_rejects_invalid_tenant_id(self):
        with pytest.raises(ValidationError):
            SelectTenantRequest(preauth_token="some-token", tenant_id="not-a-uuid")


class TestLoginResponseDiscriminatedUnion:
    """This is the one genuinely interesting test in this file — proves
    the discriminated union actually resolves to the correct concrete
    type based on `result`, not just that each type validates in
    isolation."""

    _adapter: TypeAdapter = TypeAdapter(LoginResponseBody)

    def test_authenticated_result_resolves_to_correct_type(self):
        parsed = self._adapter.validate_python(
            {
                "result": "authenticated",
                "user": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "email": "dana@example.com",
                    "display_name": "Dana",
                    "email_verified": True,
                },
                "tenant": {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "tenant_label": "Dana's Plumbing",
                },
                "membership": {"role": "owner", "permissions_version": 0},
                "access_token": "access",
                "refresh_token": "refresh",
            }
        )
        assert isinstance(parsed, AuthenticatedSessionResponse)

    def test_tenant_selection_required_result_resolves_to_correct_type(self):
        parsed = self._adapter.validate_python(
            {
                "result": "tenant_selection_required",
                "user": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "email": "dana@example.com",
                    "display_name": "Dana",
                    "email_verified": True,
                },
                "preauth_token": "preauth",
            }
        )
        assert isinstance(parsed, TenantSelectionRequiredResponse)

    def test_unrecognized_result_value_is_rejected(self):
        with pytest.raises(ValidationError):
            self._adapter.validate_python({"result": "something_else"})
