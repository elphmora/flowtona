"""tests/unit/repositories/test_user_repository.py"""

import asyncio

import pytest

from app.repositories.exceptions import DuplicateEntryError


@pytest.mark.asyncio
async def test_duplicate_email_rejected_under_concurrent_creation(user_repo):
    """Two near-simultaneous create() calls with the same (differently
    cased) email — only one should succeed. Exercises the lock-scoped
    uniqueness re-check, not just a sequential duplicate check."""
    results = await asyncio.gather(
        user_repo.create(email="Dana@Example.com", password_hash="x", display_name="A"),
        user_repo.create(email="dana@example.com", password_hash="y", display_name="B"),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], DuplicateEntryError)


@pytest.mark.asyncio
async def test_returned_models_are_copies(user_repo):
    """Mutating the returned object must not corrupt repository state —
    guards the model_copy(deep=True) discipline."""
    user = await user_repo.create(
        email="dana@example.com", password_hash="x", display_name="Dana"
    )
    user.display_name = "Corrupted"  # mutate the returned object directly

    fetched = await user_repo.get_by_id(user_id=user.id)
    assert fetched.display_name == "Dana"  # unaffected by the mutation above
