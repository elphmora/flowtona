"""
tests/unit/test_domain_models.py

Covers the invariants and structural validation on the five core domain
models (Decision 16: unit tests, model-level coverage for this branch).
Not covering repository/service behavior here — that's Phase 4's next
branch, once the Protocols and in-memory implementations exist.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.constants.roles import Role
from app.models.email_verification import EmailVerification, EmailVerificationStatus
from app.models.invitation import Invitation, InvitationStatus
from app.models.membership import MembershipStatus, TenantMembership
from app.models.refresh_token import RefreshTokenRecord, RefreshTokenStatus
from app.models.tenant import Tenant
from app.models.user import User

NOW = datetime.now(timezone.utc)


class TestUser:
    def test_valid_user_constructs(self):
        user = User(
            email="dana@example.com",
            password_hash="argon2id$...",
            display_name="Dana Whitfield",
            created_at=NOW,
        )
        assert user.email_verified is False
        assert user.id is not None

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            User(
                email="not-an-email",
                password_hash="x",
                display_name="Dana",
                created_at=NOW,
            )

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            User(
                email="dana@example.com",
                password_hash="x",
                display_name="Dana",
                created_at=NOW,
                tenant_business_name="should not be allowed here",  # type: ignore[call-arg]
            )


class TestTenant:
    def test_valid_tenant_constructs(self):
        tenant = Tenant(tenant_label="Birmingham Plumbing Co.", created_at=NOW)
        assert tenant.id is not None

    def test_extra_field_rejected(self):
        """Guards Decision 1's boundary directly: business data must not be
        addable to Tenant even by accident."""
        with pytest.raises(ValidationError):
            Tenant(
                tenant_label="Birmingham Plumbing Co.",
                created_at=NOW,
                billing_address="123 Fake Street",  # type: ignore[call-arg]
            )


class TestTenantMembership:
    def test_valid_membership_constructs_with_defaults(self):
        membership = TenantMembership(
            user_id=uuid4(),
            tenant_id=uuid4(),
            role=Role.OWNER,
            created_at=NOW,
        )
        assert membership.status == MembershipStatus.ACTIVE
        assert membership.permissions_version == 0

    def test_permissions_version_is_on_membership_not_user(self):
        """permissions_version must be tenant-scoped (ADR: a role change in
        tenant A must not imply tenant B's permissions changed)."""
        assert "permissions_version" in TenantMembership.model_fields
        assert "permissions_version" not in User.model_fields


class TestRefreshTokenRecord:
    def _base_kwargs(self, **overrides):
        kwargs = dict(
            user_id=uuid4(),
            tenant_id=uuid4(),
            family_id=uuid4(),
            token_hash="hash",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )
        kwargs.update(overrides)
        return kwargs

    def test_valid_active_token_constructs(self):
        token = RefreshTokenRecord(**self._base_kwargs())
        assert token.status == RefreshTokenStatus.ACTIVE

    def test_expires_at_must_be_after_issued_at(self):
        with pytest.raises(ValidationError):
            RefreshTokenRecord(
                **self._base_kwargs(expires_at=NOW - timedelta(minutes=1))
            )

    def test_replaced_by_token_id_rejected_unless_rotated(self):
        with pytest.raises(ValidationError):
            RefreshTokenRecord(
                **self._base_kwargs(
                    status=RefreshTokenStatus.ACTIVE,
                    replaced_by_token_id=uuid4(),
                )
            )

    def test_rotated_status_requires_rotated_at(self):
        with pytest.raises(ValidationError):
            RefreshTokenRecord(
                **self._base_kwargs(
                    status=RefreshTokenStatus.ROTATED,
                    replaced_by_token_id=uuid4(),
                    rotated_at=None,
                )
            )

    def test_rotated_status_with_rotated_at_is_valid(self):
        token = RefreshTokenRecord(
            **self._base_kwargs(
                status=RefreshTokenStatus.ROTATED,
                replaced_by_token_id=uuid4(),
                rotated_at=NOW,
            )
        )
        assert token.status == RefreshTokenStatus.ROTATED

    def test_revoked_status_requires_revoked_at(self):
        with pytest.raises(ValidationError):
            RefreshTokenRecord(
                **self._base_kwargs(status=RefreshTokenStatus.REVOKED, revoked_at=None)
            )


class TestInvitation:
    def _base_kwargs(self, **overrides):
        kwargs = dict(
            tenant_id=uuid4(),
            email="new.tech@example.com",
            role=Role.TECHNICIAN,
            token_hash="hash",
            invited_by_user_id=uuid4(),
            created_at=NOW,
            expires_at=NOW + timedelta(days=7),
        )
        kwargs.update(overrides)
        return kwargs

    def test_valid_pending_invitation_constructs(self):
        invite = Invitation(**self._base_kwargs())
        assert invite.status == InvitationStatus.PENDING

    def test_expires_at_must_be_after_created_at(self):
        with pytest.raises(ValidationError):
            Invitation(**self._base_kwargs(expires_at=NOW - timedelta(days=1)))

    def test_accepted_status_requires_accepted_at(self):
        with pytest.raises(ValidationError):
            Invitation(
                **self._base_kwargs(status=InvitationStatus.ACCEPTED, accepted_at=None)
            )

    def test_accepted_status_with_accepted_at_is_valid(self):
        invite = Invitation(
            **self._base_kwargs(status=InvitationStatus.ACCEPTED, accepted_at=NOW)
        )
        assert invite.status == InvitationStatus.ACCEPTED


class TestEmailVerification:
    def _base_kwargs(self, **overrides):
        kwargs = dict(
            user_id=uuid4(),
            email="dana@example.com",
            token_hash="hash",
            created_at=NOW,
            expires_at=NOW + timedelta(hours=24),
        )
        kwargs.update(overrides)
        return kwargs

    def test_valid_pending_verification_constructs(self):
        verification = EmailVerification(**self._base_kwargs())
        assert verification.status == EmailVerificationStatus.PENDING

    def test_expires_at_must_be_after_created_at(self):
        with pytest.raises(ValidationError):
            EmailVerification(**self._base_kwargs(expires_at=NOW - timedelta(hours=1)))

    def test_consumed_status_requires_consumed_at(self):
        with pytest.raises(ValidationError):
            EmailVerification(
                **self._base_kwargs(
                    status=EmailVerificationStatus.CONSUMED, consumed_at=None
                )
            )

    def test_revoked_status_requires_revoked_at(self):
        with pytest.raises(ValidationError):
            EmailVerification(
                **self._base_kwargs(
                    status=EmailVerificationStatus.REVOKED, revoked_at=None
                )
            )

    def test_pending_status_rejects_consumed_at(self):
        with pytest.raises(ValidationError):
            EmailVerification(**self._base_kwargs(consumed_at=NOW))

    def test_pending_status_rejects_revoked_at(self):
        with pytest.raises(ValidationError):
            EmailVerification(**self._base_kwargs(revoked_at=NOW))

    def test_consumed_status_rejects_revoked_at(self):
        with pytest.raises(ValidationError):
            EmailVerification(
                **self._base_kwargs(
                    status=EmailVerificationStatus.CONSUMED,
                    consumed_at=NOW,
                    revoked_at=NOW,
                )
            )

    def test_revoked_status_rejects_consumed_at(self):
        with pytest.raises(ValidationError):
            EmailVerification(
                **self._base_kwargs(
                    status=EmailVerificationStatus.REVOKED,
                    revoked_at=NOW,
                    consumed_at=NOW,
                )
            )

    def test_consumed_status_with_consumed_at_is_valid(self):
        verification = EmailVerification(
            **self._base_kwargs(
                status=EmailVerificationStatus.CONSUMED,
                consumed_at=NOW,
            )
        )
        assert verification.status == EmailVerificationStatus.CONSUMED
        assert verification.consumed_at == NOW

    def test_revoked_status_with_revoked_at_is_valid(self):
        verification = EmailVerification(
            **self._base_kwargs(
                status=EmailVerificationStatus.REVOKED,
                revoked_at=NOW,
            )
        )
        assert verification.status == EmailVerificationStatus.REVOKED
        assert verification.revoked_at == NOW

    def test_not_on_user_model(self):
        """Guards the actual fix: verification fields must not have landed
        on User after all."""
        assert "email_verification_token_hash" not in User.model_fields
        assert "email_verification_token_expires_at" not in User.model_fields
