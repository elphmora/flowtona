"""
app/services/refresh_token_service.py

Refresh-token lifecycle: issue (login), rotate (refresh endpoint),
revoke_current_session (logout), revoke_all_for_tenant (logout-all).
The largest and most correctness-sensitive service in this codebase —
rotation, reuse detection, and family semantics all live here.

One "now" per operation: issue() and rotate() each compute
datetime.now(timezone.utc) exactly once and derive every timestamp
that operation needs from it — not separate clock reads for issued_at/
expires_at/rotated_at within one logical moment.

rotate()'s state machine, in order:
    hash raw token
    -> lookup
       missing         -> InvalidRefreshTokenError
       revoked         -> InvalidRefreshTokenError
       expired         -> InvalidRefreshTokenError (NOT reuse — an
                           expired token is not itself evidence of theft)
       rotated         -> revoke_family() -> RefreshTokenReuseDetectedError
       active          -> attempt atomic repository.rotate()
                           success    -> return successor
                           lost race  -> repository.rotate() raises
                                         ConcurrentUpdateError;
                                         .actual_state distinguishes
                                         "rotated" (genuine reuse -> revoke
                                         family, reuse error — this
                                         revokes the WHOLE family,
                                         including whichever request
                                         actually won the race and holds
                                         a legitimate successor; that's
                                         the deliberate Decision 11
                                         tradeoff, not a bug) from
                                         "revoked"/"expired" (invalid,
                                         NOT reuse, hit during the race
                                         window)

Token hash collisions (DuplicateEntryError from create()/rotate()) are
retried with a freshly generated token, never leaked to callers —
callers of this service shouldn't need to understand repository
uniqueness exceptions for an outcome that's astronomically unlikely and
has no domain-meaningful response other than "try again."

revoke_current_session() semantics — "terminate whichever session this
token belongs to," not "prove this exact token is currently active":
    missing token  -> no-op (nothing to revoke)
    revoked token  -> no-op (already terminated, avoid redundant work)
    rotated token  -> revoke family (the session this token belonged to
                      still gets terminated, even though this specific
                      row is no longer the active leaf)
    expired token  -> revoke family (same reasoning — the session still
                      gets cleanly terminated rather than left to decay;
                      harmless either way since an expired token can't
                      be used again regardless)
    active token   -> revoke family (the normal case)
Only "missing" and "revoked" are no-ops; every other outcome results in
revoke_family() being called. Repeated logout calls are harmless in all
five cases.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.core.config import settings
from app.exceptions.refresh_token import (
    InvalidRefreshTokenError,
    RefreshTokenReuseDetectedError,
)
from app.models.refresh_token import RefreshTokenRecord, RefreshTokenStatus
from app.repositories.exceptions import (
    ConcurrentUpdateError,
    DuplicateEntryError,
    RecordNotFoundError,
)
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.security.hashing import generate_secure_token, hash_token

MAX_TOKEN_GENERATION_ATTEMPTS = 3


class RefreshTokenService:
    def __init__(self, refresh_token_repo: RefreshTokenRepository) -> None:
        self._refresh_token_repo = refresh_token_repo

    async def issue(
        self, *, user_id: UUID, tenant_id: UUID
    ) -> tuple[RefreshTokenRecord, str]:
        """New login — starts a NEW family (fresh family_id). Not used
        for rotation, which stays within the existing family via
        rotate() below."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        family_id = uuid4()

        for _ in range(MAX_TOKEN_GENERATION_ATTEMPTS):
            raw_token = generate_secure_token()
            try:
                record = await self._refresh_token_repo.create(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    family_id=family_id,
                    token_hash=hash_token(raw_token),
                    issued_at=now,
                    expires_at=expires_at,
                )
            except DuplicateEntryError:
                continue
            return record, raw_token

        raise RuntimeError(
            "Unable to generate a unique refresh token after multiple attempts."
        )

    async def rotate(self, *, raw_token: str) -> tuple[RefreshTokenRecord, str]:
        current_hash = hash_token(raw_token)
        current = await self._refresh_token_repo.get_by_token_hash(
            token_hash=current_hash
        )
        now = datetime.now(timezone.utc)

        if current is None:
            raise InvalidRefreshTokenError()

        if current.status == RefreshTokenStatus.ROTATED:
            # Reuse of an already-rotated token — genuine theft signal.
            await self._refresh_token_repo.revoke_family(
                family_id=current.family_id, revoked_at=now
            )
            raise RefreshTokenReuseDetectedError()

        if current.status == RefreshTokenStatus.REVOKED:
            raise InvalidRefreshTokenError()

        if current.expires_at <= now:
            raise InvalidRefreshTokenError()

        new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        for _ in range(MAX_TOKEN_GENERATION_ATTEMPTS):
            new_raw_token = generate_secure_token()
            try:
                successor = await self._refresh_token_repo.rotate(
                    current_token_hash=current_hash,
                    new_token_hash=hash_token(new_raw_token),
                    expires_at=new_expires_at,
                    rotated_at=now,
                )
            except DuplicateEntryError:
                continue
            except RecordNotFoundError as exc:
                # Vanished between our lookup and the atomic call — treat
                # as invalid, not reuse (see rotate()'s docstring).
                raise InvalidRefreshTokenError() from exc
            except ConcurrentUpdateError as exc:
                if exc.actual_state == RefreshTokenStatus.ROTATED.value:
                    await self._refresh_token_repo.revoke_family(
                        family_id=current.family_id, revoked_at=now
                    )
                    raise RefreshTokenReuseDetectedError() from exc
                raise InvalidRefreshTokenError() from exc
            return successor, new_raw_token

        raise RuntimeError(
            "Unable to generate a unique refresh token after multiple attempts."
        )

    async def revoke_current_session(self, *, raw_token: str) -> None:
        """Idempotent logout. Only 'missing' and 'revoked' are no-ops —
        active, rotated, and expired tokens all result in revoke_family()
        being called (see module docstring for the full breakdown)."""
        current = await self._refresh_token_repo.get_by_token_hash(
            token_hash=hash_token(raw_token)
        )
        if current is None:
            return
        if current.status == RefreshTokenStatus.REVOKED:
            return
        await self._refresh_token_repo.revoke_family(
            family_id=current.family_id, revoked_at=datetime.now(timezone.utc)
        )

    async def revoke_all_for_tenant(self, *, user_id: UUID, tenant_id: UUID) -> int:
        return await self._refresh_token_repo.revoke_all_for_tenant(
            user_id=user_id,
            tenant_id=tenant_id,
            revoked_at=datetime.now(timezone.utc),
        )
