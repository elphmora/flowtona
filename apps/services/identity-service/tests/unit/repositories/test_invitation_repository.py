"""tests/unit/repositories/test_invitation_repository.py"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.constants.roles import Role
from app.repositories.exceptions import ConcurrentUpdateError

NOW = datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_acceptance_rejects_already_accepted(invitation_repo):
    invitation = await invitation_repo.create(
        tenant_id=uuid4(),
        email="new.tech@example.com",
        role=Role.TECHNICIAN,
        token_hash="hash",
        invited_by_user_id=uuid4(),
        expires_at=NOW + timedelta(days=7),
    )
    await invitation_repo.mark_accepted(invitation_id=invitation.id, accepted_at=NOW)

    with pytest.raises(ConcurrentUpdateError):
        await invitation_repo.mark_accepted(
            invitation_id=invitation.id, accepted_at=NOW
        )


@pytest.mark.asyncio
async def test_acceptance_rejects_expired(invitation_repo):
    invitation = await invitation_repo.create(
        tenant_id=uuid4(),
        email="new.tech@example.com",
        role=Role.TECHNICIAN,
        token_hash="hash",
        invited_by_user_id=uuid4(),
        expires_at=NOW + timedelta(days=7),
    )
    too_late = NOW + timedelta(days=8)  # after expires_at

    with pytest.raises(ConcurrentUpdateError):
        await invitation_repo.mark_accepted(
            invitation_id=invitation.id, accepted_at=too_late
        )


@pytest.mark.asyncio
async def test_email_is_normalized(invitation_repo):
    """Guards the actual fix: an earlier draft stored the raw email,
    which would have broken email-matching comparisons on casing alone."""
    invitation = await invitation_repo.create(
        tenant_id=uuid4(),
        email="New.Tech@Example.COM",
        role=Role.TECHNICIAN,
        token_hash="hash",
        invited_by_user_id=uuid4(),
        expires_at=NOW + timedelta(days=7),
    )
    assert invitation.email == "new.tech@example.com"
