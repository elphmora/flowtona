

"""tests/unit/services/test_user_service.py"""

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from app.exceptions.base import IdentityInvariantError
from app.exceptions.user import EmailAlreadyRegisteredError
from app.models.user import User
from app.repositories.exceptions import DuplicateEntryError
from app.services.user_service import UserService

# Applies to every test in this module — every method is async, and
# pytest-asyncio's strict mode (see pytest.ini) requires explicit
# marking, unlike PermissionService's tests which were pure sync logic.
pytestmark = pytest.mark.asyncio


@pytest.fixture
def service(user_repo) -> UserService:
    return UserService(user_repo)


class _RaceyDuplicateUserRepo:
    """A minimal fake, not the real InMemoryUserRepository — used to
    exercise the race-window translation path independently of the real
    implementation's actual concurrency behavior. get_by_email() always
    reports no existing user (simulating a pre-check that ran before a
    concurrent request's create() won the race), but create() still
    raises DuplicateEntryError, as the real repository's own final
    guard would if a concurrent request actually beat this one to it."""

    async def get_by_email(self, *, email: str) -> User | None:
        return None

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        email_verified: bool = False,
    ) -> User:
        raise DuplicateEntryError(entity="user", field="email")

    async def get_by_id(self, *, user_id: UUID) -> User | None:
        raise NotImplementedError("not exercised in this test")

    async def update(self, *, user: User) -> User:
        raise NotImplementedError("not exercised in this test")


class TestCreate:
    async def test_creates_user_with_verified_false_by_default(self, service):
        user = await service.create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        assert user.email_verified is False
        assert user.password_hash != "hunter2"  # never store the plaintext

    async def test_creates_user_with_email_verified_true_when_requested(self, service):
        """Invitation acceptance by a new user path (Invariant 9)."""
        user = await service.create(
            email="new.tech@example.com",
            password="hunter2",
            display_name="New Tech",
            email_verified=True,
        )
        assert user.email_verified is True

    async def test_precheck_duplicate_raises_domain_exception(self, service):
        await service.create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        with pytest.raises(EmailAlreadyRegisteredError):
            await service.create(
                email="Dana@Example.com", password="different", display_name="Dupe"
            )

    async def test_precheck_duplicate_does_not_hash_password(self, service):
        """The whole point of checking existence before hashing: don't
        pay Argon2id's deliberate cost for an already-known duplicate."""
        await service.create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        with patch("app.services.user_service.hash_password") as mock_hash:
            with pytest.raises(EmailAlreadyRegisteredError):
                await service.create(
                    email="dana@example.com",
                    password="different",
                    display_name="Dupe",
                )
            mock_hash.assert_not_called()

    async def test_race_window_duplicate_is_translated_independent_of_precheck(self):
        """Exercises the race the pre-check CANNOT close: get_by_email()
        reports no duplicate, but create() still raises
        DuplicateEntryError (simulating a concurrent request that won
        the race between this call's pre-check and its own create()).
        Must still surface as the domain exception, not the raw
        repository exception."""
        service = UserService(_RaceyDuplicateUserRepo())
        with pytest.raises(EmailAlreadyRegisteredError):
            await service.create(
                email="dana@example.com", password="hunter2", display_name="Dana"
            )


class TestLookup:
    async def test_get_by_id_and_get_by_email_roundtrip(self, service):
        created = await service.create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        by_id = await service.get_by_id(user_id=created.id)
        by_email = await service.get_by_email(email="dana@example.com")
        assert by_id.id == created.id
        assert by_email.id == created.id

    async def test_get_by_id_returns_none_for_unknown_user(self, service):
        assert await service.get_by_id(user_id=uuid4()) is None


class TestMarkEmailVerified:
    async def test_flips_email_verified_to_true(self, service):
        user = await service.create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        assert user.email_verified is False

        updated = await service.mark_email_verified(
            user_id=user.id, expected_email="dana@example.com"
        )
        assert updated.email_verified is True

    async def test_is_idempotent_when_already_verified(self, service):
        user = await service.create(
            email="dana@example.com",
            password="hunter2",
            display_name="Dana",
            email_verified=True,
        )
        result = await service.mark_email_verified(
            user_id=user.id, expected_email="dana@example.com"
        )
        assert result.email_verified is True
        assert result.id == user.id

    async def test_raises_invariant_error_on_email_mismatch(self, service):
        user = await service.create(
            email="dana@example.com", password="hunter2", display_name="Dana"
        )
        with pytest.raises(IdentityInvariantError):
            await service.mark_email_verified(
                user_id=user.id, expected_email="someone.else@example.com"
            )

    async def test_raises_invariant_error_on_unknown_user(self, service):
        with pytest.raises(IdentityInvariantError):
            await service.mark_email_verified(
                user_id=uuid4(), expected_email="dana@example.com"
            )