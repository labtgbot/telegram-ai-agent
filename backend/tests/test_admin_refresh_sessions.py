"""Tests for persisted admin refresh-token sessions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.jwt import create_refresh_token, decode_token
from app.models import AdminRefreshSession, User
from app.services.admin_refresh_sessions import (
    RefreshSessionReusedError,
    cleanup_refresh_sessions,
    create_refresh_session,
    hash_refresh_jti,
    revoke_refresh_session,
    rotate_refresh_session,
)

SECRET = "test-refresh-session-secret"


def _issue_refresh_claims(user: User, *, ttl_seconds: int = 600):
    token = create_refresh_token(
        subject=user.id,
        role=user.role,
        secret=SECRET,
        ttl_seconds=ttl_seconds,
    )
    return decode_token(token, secret=SECRET, expected_type="refresh")


async def _make_admin(session: AsyncSession, telegram_id: int) -> User:
    user = User(
        telegram_id=telegram_id,
        referral_code=f"ARS-{telegram_id}",
        role="super_admin",
    )
    session.add(user)
    await session.flush()
    return user


def test_hash_refresh_jti_is_stable_and_secret_scoped() -> None:
    first = hash_refresh_jti("jti-1", secret=SECRET)
    second = hash_refresh_jti("jti-1", secret=SECRET)
    other_secret = hash_refresh_jti("jti-1", secret="other-secret")

    assert first == second
    assert first != "jti-1"
    assert first != other_secret
    assert len(first) == 64


@pytest.mark.asyncio
async def test_rotate_refresh_session_consumes_current_and_creates_successor(db_session):
    user = await _make_admin(db_session, telegram_id=7_211_001)
    current_claims = _issue_refresh_claims(user)
    current = await create_refresh_session(
        db_session,
        claims=current_claims,
        user=user,
        secret=SECRET,
    )
    next_claims = _issue_refresh_claims(user)

    successor = await rotate_refresh_session(
        db_session,
        current_claims=current_claims,
        next_claims=next_claims,
        user=user,
        secret=SECRET,
    )

    assert current.used_at is not None
    assert current.revoked_at is not None
    assert current.revocation_reason == "rotated"
    assert current.replaced_by_session_id == successor.id
    assert successor.parent_session_id == current.id


@pytest.mark.asyncio
async def test_reusing_rotated_refresh_session_revokes_successor_chain(db_session):
    user = await _make_admin(db_session, telegram_id=7_211_002)
    current_claims = _issue_refresh_claims(user)
    current = await create_refresh_session(
        db_session,
        claims=current_claims,
        user=user,
        secret=SECRET,
    )
    next_claims = _issue_refresh_claims(user)
    successor = await rotate_refresh_session(
        db_session,
        current_claims=current_claims,
        next_claims=next_claims,
        user=user,
        secret=SECRET,
    )

    with pytest.raises(RefreshSessionReusedError):
        await rotate_refresh_session(
            db_session,
            current_claims=current_claims,
            next_claims=_issue_refresh_claims(user),
            user=user,
            secret=SECRET,
        )

    await db_session.refresh(successor)
    assert current.used_at is not None
    assert successor.revoked_at is not None
    assert successor.revocation_reason == "reuse_detected"


@pytest.mark.asyncio
async def test_revoke_refresh_session_invalidates_active_session(db_session):
    user = await _make_admin(db_session, telegram_id=7_211_003)
    claims = _issue_refresh_claims(user)
    refresh_session = await create_refresh_session(
        db_session,
        claims=claims,
        user=user,
        secret=SECRET,
    )

    revoked = await revoke_refresh_session(
        db_session,
        claims=claims,
        secret=SECRET,
        reason="logout",
    )

    assert revoked is True
    assert refresh_session.revoked_at is not None
    assert refresh_session.revocation_reason == "logout"


@pytest.mark.asyncio
async def test_cleanup_refresh_sessions_deletes_expired_and_old_revoked_rows(db_session):
    user = await _make_admin(db_session, telegram_id=7_211_005)
    now = datetime(2026, 6, 15, 12, tzinfo=UTC)
    old_revoked_at = now - timedelta(days=8)
    recent_revoked_at = now - timedelta(hours=1)

    rows = [
        AdminRefreshSession(
            user_id=user.id,
            jti_hash="expired-active",
            role=user.role,
            issued_at=now - timedelta(days=8),
            expires_at=now - timedelta(seconds=1),
        ),
        AdminRefreshSession(
            user_id=user.id,
            jti_hash="old-revoked",
            role=user.role,
            issued_at=now - timedelta(days=8),
            expires_at=now + timedelta(days=1),
            revoked_at=old_revoked_at,
            revocation_reason="logout",
        ),
        AdminRefreshSession(
            user_id=user.id,
            jti_hash="recent-revoked",
            role=user.role,
            issued_at=now - timedelta(hours=2),
            expires_at=now + timedelta(days=1),
            revoked_at=recent_revoked_at,
            revocation_reason="logout",
        ),
        AdminRefreshSession(
            user_id=user.id,
            jti_hash="active",
            role=user.role,
            issued_at=now,
            expires_at=now + timedelta(days=1),
        ),
    ]
    db_session.add_all(rows)
    await db_session.flush()

    deleted = await cleanup_refresh_sessions(
        db_session,
        now=now,
        revoked_retention_seconds=7 * 24 * 60 * 60,
    )

    assert deleted == 2
    remaining = (
        (
            await db_session.execute(
                select(AdminRefreshSession.jti_hash).where(AdminRefreshSession.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert set(remaining) == {"recent-revoked", "active"}


@pytest.mark.asyncio
async def test_concurrent_refresh_attempts_create_one_successor(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    user_id: int | None = None
    current_session_id: int | None = None

    try:
        async with factory() as setup:
            user = await _make_admin(setup, telegram_id=7_211_004)
            current_claims = _issue_refresh_claims(user)
            current = await create_refresh_session(
                setup,
                claims=current_claims,
                user=user,
                secret=SECRET,
            )
            user_id = user.id
            current_session_id = current.id
            await setup.commit()

        async def attempt() -> str:
            async with factory() as session:
                result = await session.execute(select(User).where(User.id == user_id))
                user = result.scalar_one()
                try:
                    await rotate_refresh_session(
                        session,
                        current_claims=current_claims,
                        next_claims=_issue_refresh_claims(user),
                        user=user,
                        secret=SECRET,
                    )
                except RefreshSessionReusedError:
                    await session.commit()
                    return "reused"
                await session.commit()
                return "rotated"

        results = await asyncio.gather(attempt(), attempt())
        assert sorted(results) == ["reused", "rotated"]

        async with factory() as verify:
            rows = (
                (
                    await verify.execute(
                        select(AdminRefreshSession).where(AdminRefreshSession.user_id == user_id)
                    )
                )
                .scalars()
                .all()
            )
        successors = [row for row in rows if row.parent_session_id == current_session_id]
        assert len(successors) == 1
    finally:
        if user_id is not None:
            async with factory() as cleanup:
                await cleanup.execute(
                    delete(AdminRefreshSession).where(AdminRefreshSession.user_id == user_id)
                )
                await cleanup.execute(delete(User).where(User.id == user_id))
                await cleanup.commit()
