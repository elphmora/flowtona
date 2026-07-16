"""
app/repositories/in_memory/user_repository.py

In-memory implementation of UserRepository (Protocol, Decision 9).
Structural typing means this class doesn't need to inherit from
UserRepository explicitly — conformance is checked by mypy/pyright, not
enforced at runtime.

Establishes the pattern the other five in-memory repositories follow:
- one shared InMemoryIdentityStore instance, passed in via constructor
- lock scoped to mutations (create/update), not plain reads
- create() re-checks uniqueness INSIDE the lock as the final guard, not
  just trusting the service layer's earlier get_by_email() call —
  otherwise two near-simultaneous signups with the same email could both
  pass an earlier check and both reach create()
- model_copy(deep=True) on every read AND write — User is mutable
  (validate_assignment=True, not frozen), so returning or storing the
  exact same object reference would let a caller mutate repository state
  without ever calling update()
- email is normalized (lowercased, stripped) before every read and write
  that touches user_id_by_email, so the uniqueness constraint is on the
  normalized form, not whatever casing a client happened to submit
- no Clock abstraction (considered and deferred 2026-07-14) —
  datetime.now(timezone.utc) directly; nothing currently needs
  deterministic time control in tests
"""

from datetime import datetime, timezone
from uuid import UUID

from app.models.user import User
from app.repositories.exceptions import DuplicateEntryError, RecordNotFoundError
from app.repositories.in_memory.store import InMemoryIdentityStore
from app.utils.email import normalise_email


class InMemoryUserRepository:
    def __init__(self, store: InMemoryIdentityStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
    ) -> User:
        normalized = normalise_email(email)

        async with self._store.lock:
            if normalized in self._store.user_id_by_email:
                raise DuplicateEntryError(entity="user", field="email")

            user = User(
                email=normalized,
                password_hash=password_hash,
                display_name=display_name,
                created_at=datetime.now(timezone.utc),
            )
            stored = user.model_copy(deep=True)
            self._store.users_by_id[user.id] = stored
            self._store.user_id_by_email[normalized] = user.id
            return stored.model_copy(deep=True)

    async def get_by_id(self, *, user_id: UUID) -> User | None:
        user = self._store.users_by_id.get(user_id)
        return user.model_copy(deep=True) if user else None

    async def get_by_email(self, *, email: str) -> User | None:
        normalized = normalise_email(email)
        user_id = self._store.user_id_by_email.get(normalized)
        if user_id is None:
            return None
        return self._store.users_by_id[user_id].model_copy(deep=True)

    async def update(self, *, user: User) -> User:
        async with self._store.lock:
            if user.id not in self._store.users_by_id:
                raise RecordNotFoundError(entity="user", identifier=user.id)

            existing = self._store.users_by_id[user.id]
            if existing.email != user.email:
                # Defensive guard, not a designed feature: changing a
                # user's email isn't decided anywhere in the ADR (see
                # models/email_verification.py's docstring on this exact
                # point). Silently allowing it here would corrupt
                # user_id_by_email without anything having actually
                # designed what "changing email" should do.
                raise NotImplementedError(
                    "Changing a user's email via update() is not supported "
                    "— email change is not a decided feature."
                )

            self._store.users_by_id[user.id] = user.model_copy(deep=True)
            return user.model_copy(deep=True)
