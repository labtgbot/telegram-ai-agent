"""Unit tests for the admin login code lifecycle (Redis-backed)."""
from __future__ import annotations

import pytest

from app.services.admin_login import (
    AdminLoginCode,
    LoginCodeAttemptsExceededError,
    LoginCodeInvalidError,
    LoginCodeMissingError,
    _generate_numeric_code,
    request_admin_login,
    verify_admin_login,
)


class FakeRedis:
    """Minimal in-memory async Redis substitute."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                removed += 1
        return removed

    async def incr(self, key: str) -> int:
        cur = int(self.store.get(key, 0)) + 1
        self.store[key] = str(cur)
        return cur

    async def expire(self, key: str, seconds: int) -> bool:
        return key in self.store


def test_generate_numeric_code_length_and_digits() -> None:
    code = _generate_numeric_code(6)
    assert len(code) == 6
    assert code.isdigit()


def test_generate_numeric_code_rejects_bad_length() -> None:
    with pytest.raises(ValueError):
        _generate_numeric_code(3)
    with pytest.raises(ValueError):
        _generate_numeric_code(11)


@pytest.mark.asyncio
async def test_request_then_verify_happy_path() -> None:
    redis = FakeRedis()
    code = await request_admin_login(
        redis,
        telegram_id=10,
        secret="s",
        ttl_seconds=60,
        code_length=6,
    )
    assert isinstance(code, AdminLoginCode)
    assert len(code.code) == 6

    await verify_admin_login(
        redis,
        telegram_id=10,
        code=code.code,
        secret="s",
        max_attempts=5,
        ttl_seconds=60,
    )

    # Code is single-use — second verify must fail.
    with pytest.raises(LoginCodeMissingError):
        await verify_admin_login(
            redis,
            telegram_id=10,
            code=code.code,
            secret="s",
            max_attempts=5,
            ttl_seconds=60,
        )


@pytest.mark.asyncio
async def test_verify_rejects_wrong_code_and_tracks_attempts() -> None:
    redis = FakeRedis()
    code = await request_admin_login(
        redis, telegram_id=11, secret="s", ttl_seconds=60, code_length=6
    )
    wrong = "000000" if code.code != "000000" else "000001"
    for _ in range(3):
        with pytest.raises(LoginCodeInvalidError):
            await verify_admin_login(
                redis,
                telegram_id=11,
                code=wrong,
                secret="s",
                max_attempts=5,
                ttl_seconds=60,
            )
    # Real code still works.
    await verify_admin_login(
        redis,
        telegram_id=11,
        code=code.code,
        secret="s",
        max_attempts=5,
        ttl_seconds=60,
    )


@pytest.mark.asyncio
async def test_verify_explodes_after_max_attempts() -> None:
    redis = FakeRedis()
    code = await request_admin_login(
        redis, telegram_id=12, secret="s", ttl_seconds=60, code_length=6
    )
    wrong = "000000" if code.code != "000000" else "000001"
    for _ in range(2):
        with pytest.raises(LoginCodeInvalidError):
            await verify_admin_login(
                redis,
                telegram_id=12,
                code=wrong,
                secret="s",
                max_attempts=2,
                ttl_seconds=60,
            )
    with pytest.raises(LoginCodeAttemptsExceededError):
        await verify_admin_login(
            redis,
            telegram_id=12,
            code=wrong,
            secret="s",
            max_attempts=2,
            ttl_seconds=60,
        )
    # Code wiped — even correct value must now miss.
    with pytest.raises(LoginCodeMissingError):
        await verify_admin_login(
            redis,
            telegram_id=12,
            code=code.code,
            secret="s",
            max_attempts=2,
            ttl_seconds=60,
        )


@pytest.mark.asyncio
async def test_verify_rejects_non_numeric_code() -> None:
    redis = FakeRedis()
    await request_admin_login(
        redis, telegram_id=13, secret="s", ttl_seconds=60, code_length=6
    )
    with pytest.raises(LoginCodeInvalidError):
        await verify_admin_login(
            redis,
            telegram_id=13,
            code="abcdef",
            secret="s",
            max_attempts=5,
            ttl_seconds=60,
        )


@pytest.mark.asyncio
async def test_verify_with_no_outstanding_code() -> None:
    redis = FakeRedis()
    with pytest.raises(LoginCodeMissingError):
        await verify_admin_login(
            redis,
            telegram_id=999,
            code="123456",
            secret="s",
            max_attempts=5,
            ttl_seconds=60,
        )
