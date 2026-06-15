"""Admin refresh-token session lifecycle.

Refresh JWTs remain signed stateless tokens, but their ``jti`` is persisted
server-side so rotation and logout can revoke individual sessions.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import TokenClaims
from app.models.admin_refresh_session import AdminRefreshSession
from app.models.user import User


class RefreshSessionError(Exception):
    """Base class for refresh-session validation failures."""


class RefreshSessionUnknownError(RefreshSessionError):
    """The refresh token has no persisted server-side session."""


class RefreshSessionExpiredError(RefreshSessionError):
    """The persisted session is past its expiry."""


class RefreshSessionRevokedError(RefreshSessionError):
    """The session has been explicitly revoked."""


class RefreshSessionReusedError(RefreshSessionError):
    """A token already consumed by rotation was presented again."""


class RefreshSessionUserMismatchError(RefreshSessionError):
    """The JWT subject does not match the persisted session owner."""


def hash_refresh_jti(jti: str, *, secret: str) -> str:
    """Return the stable, non-reversible DB representation for a refresh ``jti``."""
    return hmac.new(secret.encode(), jti.encode(), hashlib.sha256).hexdigest()


def _claims_datetime(value: int) -> datetime:
    return datetime.fromtimestamp(value, UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def create_refresh_session(
    session: AsyncSession,
    *,
    claims: TokenClaims,
    user: User,
    secret: str,
    parent_session_id: int | None = None,
) -> AdminRefreshSession:
    """Persist a newly minted refresh token's ``jti``."""
    refresh_session = AdminRefreshSession(
        user_id=user.id,
        jti_hash=hash_refresh_jti(claims.jti, secret=secret),
        role=user.role,
        issued_at=_claims_datetime(claims.iat),
        expires_at=_claims_datetime(claims.exp),
        parent_session_id=parent_session_id,
    )
    session.add(refresh_session)
    await session.flush()
    return refresh_session


async def _find_refresh_session_for_update(
    session: AsyncSession,
    *,
    jti: str,
    secret: str,
) -> AdminRefreshSession | None:
    result = await session.execute(
        select(AdminRefreshSession)
        .where(AdminRefreshSession.jti_hash == hash_refresh_jti(jti, secret=secret))
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _revoke_descendant_chain(
    session: AsyncSession,
    *,
    root_session_id: int,
    now: datetime,
    reason: str,
) -> None:
    pending = [root_session_id]
    seen: set[int] = set()
    while pending:
        parent_id = pending.pop()
        if parent_id in seen:
            continue
        seen.add(parent_id)
        result = await session.execute(
            select(AdminRefreshSession).where(AdminRefreshSession.parent_session_id == parent_id)
        )
        children = result.scalars().all()
        for child in children:
            pending.append(child.id)
            if child.revoked_at is None:
                child.revoked_at = now
                child.revocation_reason = reason
    await session.flush()


def _validate_active_session(
    refresh_session: AdminRefreshSession,
    *,
    claims: TokenClaims,
    user: User,
    now: datetime,
) -> None:
    if refresh_session.user_id != user.id or str(refresh_session.user_id) != claims.sub:
        raise RefreshSessionUserMismatchError("refresh session user mismatch")
    if refresh_session.used_at is not None:
        raise RefreshSessionReusedError("refresh token already used")
    if refresh_session.revoked_at is not None:
        raise RefreshSessionRevokedError("refresh token revoked")
    if refresh_session.expires_at <= now:
        raise RefreshSessionExpiredError("refresh session expired")


async def rotate_refresh_session(
    session: AsyncSession,
    *,
    current_claims: TokenClaims,
    next_claims: TokenClaims,
    user: User,
    secret: str,
) -> AdminRefreshSession:
    """Consume the current refresh session and persist its successor atomically."""
    now = _utcnow()
    current = await _find_refresh_session_for_update(
        session,
        jti=current_claims.jti,
        secret=secret,
    )
    if current is None:
        raise RefreshSessionUnknownError("refresh session not found")

    try:
        _validate_active_session(current, claims=current_claims, user=user, now=now)
    except RefreshSessionReusedError:
        await _revoke_descendant_chain(
            session,
            root_session_id=current.id,
            now=now,
            reason="reuse_detected",
        )
        raise

    successor = await create_refresh_session(
        session,
        claims=next_claims,
        user=user,
        secret=secret,
        parent_session_id=current.id,
    )
    current.used_at = now
    current.revoked_at = now
    current.revocation_reason = "rotated"
    current.replaced_by_session_id = successor.id
    await session.flush()
    return successor


async def revoke_refresh_session(
    session: AsyncSession,
    *,
    claims: TokenClaims,
    secret: str,
    reason: str = "logout",
) -> bool:
    """Revoke the refresh session identified by ``claims``.

    Returns ``False`` for unknown sessions so logout can stay idempotent.
    Reusing an already rotated token revokes the successor chain and raises.
    """
    now = _utcnow()
    refresh_session = await _find_refresh_session_for_update(
        session,
        jti=claims.jti,
        secret=secret,
    )
    if refresh_session is None:
        return False
    if refresh_session.used_at is not None:
        await _revoke_descendant_chain(
            session,
            root_session_id=refresh_session.id,
            now=now,
            reason="reuse_detected",
        )
        raise RefreshSessionReusedError("refresh token already used")
    if refresh_session.revoked_at is None:
        refresh_session.revoked_at = now
        refresh_session.revocation_reason = reason
        await session.flush()
    return True


async def cleanup_refresh_sessions(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    revoked_retention_seconds: int,
) -> int:
    """Delete stale persisted refresh sessions.

    Expired sessions can be removed immediately. Revoked sessions are retained
    for a full refresh-token TTL so replay detection can still revoke successor
    chains while the original JWT could otherwise validate.
    """
    if revoked_retention_seconds < 0:
        raise ValueError("revoked_retention_seconds must be non-negative")

    moment = now or _utcnow()
    revoked_before = moment - timedelta(seconds=revoked_retention_seconds)
    expired_result = cast(
        CursorResult[Any],
        await session.execute(
            delete(AdminRefreshSession).where(AdminRefreshSession.expires_at <= moment)
        ),
    )
    revoked_result = cast(
        CursorResult[Any],
        await session.execute(
            delete(AdminRefreshSession).where(
                AdminRefreshSession.revoked_at <= revoked_before
            )
        ),
    )
    return int(expired_result.rowcount or 0) + int(revoked_result.rowcount or 0)
