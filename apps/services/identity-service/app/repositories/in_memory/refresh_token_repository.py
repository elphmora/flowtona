"""
app/repositories/in_memory/refresh_token_repository.py

In-memory implementation of RefreshTokenRepository (Protocol, Decision
9). The most detailed of the six adapters — token rotation, reuse
detection, and both revocation scopes all live here.

mark_rotated() atomically requires status == ACTIVE — this is the
repository-level guard against two concurrent refresh requests both
rotating the same token (the Protocol's documented requirement).

revoke_family() and revoke_all_active() touch every non-revoked row in
scope, including rotated ancestors, not just active leaves — matches
the Protocol's explicit semantics (see that file's docstring on why
"every non-revoked row" matters, not just the current one).

revoke_all_active() has no dedicated (user_id, tenant_id) index — linear
scan over refresh_tokens_by_id, filtered. Only called on logout-all,
which is rare; a dedicated index here would be overhead with no real
payoff, same reasoning as EmailVerificationRepository's
revoke_pending_for_user().

All state transitions reconstruct through the constructor
(model_dump() + override + RefreshTokenRecord(**data)), not
model_copy(update=...) — same validation reasoning as the other two
repositories with lifecycle validators.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.models.refresh_token import RefreshTokenRecord, RefreshTokenStatus
from app.repositories.exceptions import (
    ConcurrentUpdateError,
    DuplicateEntryError,
    RecordNotFoundError,
)
from app.repositories.in_memory.store import InMemoryIdentityStore


class InMemoryRefreshTokenRepository:
    def __init__(self, store: InMemoryIdentityStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        family_id: UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        async with self._store.lock:
            if token_hash in self._store.refresh_token_id_by_hash:
                raise DuplicateEntryError(entity="refresh_token", field="token_hash")

            token = RefreshTokenRecord(
                user_id=user_id,
                tenant_id=tenant_id,
                family_id=family_id,
                token_hash=token_hash,
                issued_at=datetime.now(timezone.utc),
                expires_at=expires_at,
            )
            stored = token.model_copy(deep=True)
            self._store.refresh_tokens_by_id[token.id] = stored
            self._store.refresh_token_id_by_hash[token_hash] = token.id
            self._store.refresh_token_ids_by_family.setdefault(family_id, set()).add(
                token.id
            )
            return stored.model_copy(deep=True)

    async def get_by_token_hash(self, *, token_hash: str) -> RefreshTokenRecord | None:
        token_id = self._store.refresh_token_id_by_hash.get(token_hash)
        if token_id is None:
            return None
        return self._store.refresh_tokens_by_id[token_id].model_copy(deep=True)

    async def mark_rotated(
        self,
        *,
        token_hash: str,
        replaced_by_token_id: UUID,
        rotated_at: datetime,
    ) -> RefreshTokenRecord:
        async with self._store.lock:
            token_id = self._store.refresh_token_id_by_hash.get(token_hash)
            if token_id is None:
                raise RecordNotFoundError(entity="refresh_token", identifier=token_hash)

            token = self._store.refresh_tokens_by_id[token_id]
            if token.status != RefreshTokenStatus.ACTIVE:
                raise ConcurrentUpdateError(
                    entity="refresh_token",
                    identifier=token_id,
                    expected_state="active",
                    actual_state=token.status.value,
                )

            data = token.model_dump()
            data["status"] = RefreshTokenStatus.ROTATED
            data["rotated_at"] = rotated_at
            data["replaced_by_token_id"] = replaced_by_token_id
            updated = RefreshTokenRecord(**data)

            self._store.refresh_tokens_by_id[token_id] = updated.model_copy(deep=True)
            return updated.model_copy(deep=True)

    async def revoke_family(self, *, family_id: UUID, revoked_at: datetime) -> int:
        async with self._store.lock:
            ids = self._store.refresh_token_ids_by_family.get(family_id, set())
            count = 0
            for token_id in ids:
                token = self._store.refresh_tokens_by_id[token_id]
                if token.status == RefreshTokenStatus.REVOKED:
                    continue
                data = token.model_dump()
                data["status"] = RefreshTokenStatus.REVOKED
                data["revoked_at"] = revoked_at
                updated = RefreshTokenRecord(**data)
                self._store.refresh_tokens_by_id[token_id] = updated.model_copy(
                    deep=True
                )
                count += 1
            return count

    async def revoke_all_active(
        self, *, user_id: UUID, tenant_id: UUID, revoked_at: datetime
    ) -> int:
        async with self._store.lock:
            count = 0
            for token_id, token in list(self._store.refresh_tokens_by_id.items()):
                if (
                    token.user_id == user_id
                    and token.tenant_id == tenant_id
                    and token.status != RefreshTokenStatus.REVOKED
                ):
                    data = token.model_dump()
                    data["status"] = RefreshTokenStatus.REVOKED
                    data["revoked_at"] = revoked_at
                    updated = RefreshTokenRecord(**data)
                    self._store.refresh_tokens_by_id[token_id] = updated.model_copy(
                        deep=True
                    )
                    count += 1
            return count
