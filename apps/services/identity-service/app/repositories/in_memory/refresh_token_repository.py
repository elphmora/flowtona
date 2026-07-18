"""
app/repositories/in_memory/refresh_token_repository.py

In-memory implementation of RefreshTokenRepository (Protocol, Decision
9). rotate() is the one genuinely complex method here — see the
Protocol's docstring for the full correctness reasoning.

create() takes issued_at as an explicit parameter now, not generated
internally — see the Protocol docstring on why.

create() defensively rejects being called with a family_id that
already has an active token — create() is for starting a NEW family
(login), not continuing one (that's rotate()'s job).

All state transitions reconstruct through the constructor (model_dump()
+ override), never model_copy(update=...), for the same validation
reason as every other repository with lifecycle validators in this
codebase.
"""

from datetime import datetime
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
        issued_at: datetime,
        expires_at: datetime,
    ) -> RefreshTokenRecord:
        async with self._store.lock:
            if token_hash in self._store.refresh_token_id_by_hash:
                raise DuplicateEntryError(entity="refresh_token", field="token_hash")

            existing_family_ids = self._store.refresh_token_ids_by_family.get(
                family_id, set()
            )
            for existing_id in existing_family_ids:
                if (
                    self._store.refresh_tokens_by_id[existing_id].status
                    == RefreshTokenStatus.ACTIVE
                ):
                    raise ValueError(
                        f"family {family_id} already has an active token — "
                        "create() starts a NEW family (one per login/device, "
                        "Invariant 10); use rotate() to continue an existing "
                        "family instead of calling create() again for it"
                    )

            token = RefreshTokenRecord(
                user_id=user_id,
                tenant_id=tenant_id,
                family_id=family_id,
                token_hash=token_hash,
                issued_at=issued_at,
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

    async def rotate(
        self,
        *,
        current_token_hash: str,
        new_token_hash: str,
        expires_at: datetime,
        rotated_at: datetime,
    ) -> RefreshTokenRecord:
        async with self._store.lock:
            current_id = self._store.refresh_token_id_by_hash.get(current_token_hash)
            if current_id is None:
                raise RecordNotFoundError(
                    entity="refresh_token", identifier=current_token_hash
                )

            current = self._store.refresh_tokens_by_id[current_id]

            if current.status != RefreshTokenStatus.ACTIVE:
                raise ConcurrentUpdateError(
                    entity="refresh_token",
                    identifier=current_id,
                    expected_state="active",
                    actual_state=current.status.value,
                )

            if current.expires_at <= rotated_at:
                raise ConcurrentUpdateError(
                    entity="refresh_token",
                    identifier=current_id,
                    expected_state="unexpired",
                    actual_state="expired",
                )

            if new_token_hash in self._store.refresh_token_id_by_hash:
                raise DuplicateEntryError(entity="refresh_token", field="token_hash")

            successor = RefreshTokenRecord(
                user_id=current.user_id,
                tenant_id=current.tenant_id,
                family_id=current.family_id,
                token_hash=new_token_hash,
                issued_at=rotated_at,
                expires_at=expires_at,
            )

            rotated_data = current.model_dump()
            rotated_data["status"] = RefreshTokenStatus.ROTATED
            rotated_data["rotated_at"] = rotated_at
            rotated_data["replaced_by_token_id"] = successor.id
            rotated_current = RefreshTokenRecord(**rotated_data)

            self._store.refresh_tokens_by_id[current_id] = rotated_current.model_copy(
                deep=True
            )
            self._store.refresh_tokens_by_id[successor.id] = successor.model_copy(
                deep=True
            )
            self._store.refresh_token_id_by_hash[new_token_hash] = successor.id
            self._store.refresh_token_ids_by_family[current.family_id].add(successor.id)

            return successor.model_copy(deep=True)

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

    async def revoke_all_for_tenant(
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
